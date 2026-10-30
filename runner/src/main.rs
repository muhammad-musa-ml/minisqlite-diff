//! msq-runner: a line-oriented driver for cursor/minisqlite.
//!
//! The differential harness (Python) cannot call a Rust library directly, so this
//! binary wraps `minisqlite::Connection` behind a tiny stdin/stdout protocol.
//! One command per line, one JSON object per reply line. SQL travels as hex so a
//! statement can hold newlines, tabs and quotes.
//!
//!   RESET                  fresh in-memory database
//!   OPEN <hex path>        open (or create) the database file at the path
//!   E <hex sql>            Connection::execute
//!   Q <hex sql>            Connection::query
//!
//! Replies:
//!   {"ok":true}
//!   {"ok":true,"cols":[...],"rows":[[v,...],...]}      v = ["n"] | ["i","123"] | ["r","<f64 bits hex>"] | ["t","text"] | ["b","<hex>"]
//!   {"err":"<Display text>","code":<primary code>}
//!   {"panic":"<message>"}                              the connection is reset after a panic
//!
//! Reals travel as their IEEE-754 bit pattern so NaN, -0.0 and the last digit of
//! a float survive the trip and the comparison is exact.

use minisqlite::{Connection, Error, Value};
use std::io::{self, BufRead, Write};
use std::panic::{self, AssertUnwindSafe};
use std::path::Path;

fn unhex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len() / 2);
    for pair in b.chunks(2) {
        let hi = (pair[0] as char).to_digit(16)?;
        let lo = (pair[1] as char).to_digit(16)?;
        out.push((hi * 16 + lo) as u8);
    }
    Some(out)
}

fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

fn value_json(v: &Value) -> String {
    match v {
        Value::Null => "[\"n\"]".to_string(),
        Value::Integer(i) => format!("[\"i\",\"{i}\"]"),
        Value::Real(f) => format!("[\"r\",\"{:016x}\"]", f.to_bits()),
        Value::Text(s) => format!("[\"t\",\"{}\"]", esc(s)),
        Value::Blob(b) => format!("[\"b\",\"{}\"]", hex(b)),
    }
}

fn err_json(e: &Error) -> String {
    format!("{{\"err\":\"{}\",\"code\":{}}}", esc(&e.to_string()), e.primary_code())
}

fn fresh() -> Connection {
    Connection::open_in_memory().expect("open_in_memory")
}

fn run(db: &mut Connection, op: &str, sql: &str) -> String {
    match op {
        "E" => match db.execute(sql) {
            Ok(()) => "{\"ok\":true}".to_string(),
            Err(e) => err_json(&e),
        },
        _ => match db.query(sql) {
            Ok(qr) => {
                let cols: Vec<String> = qr.columns.iter().map(|c| format!("\"{}\"", esc(c))).collect();
                let rows: Vec<String> = qr
                    .rows
                    .iter()
                    .map(|r| {
                        let cells: Vec<String> = r.iter().map(value_json).collect();
                        format!("[{}]", cells.join(","))
                    })
                    .collect();
                format!("{{\"ok\":true,\"cols\":[{}],\"rows\":[{}]}}", cols.join(","), rows.join(","))
            }
            Err(e) => err_json(&e),
        },
    }
}

fn main() {
    // A panic inside the engine is a finding, not a crash of the harness.
    panic::set_hook(Box::new(|_| {}));
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let mut db = fresh();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        let line = line.trim_end();
        if line.is_empty() {
            continue;
        }
        let (op, rest) = match line.split_once(' ') {
            Some((o, r)) => (o, r),
            None => (line, ""),
        };
        let reply = match op {
            "RESET" => {
                db = fresh();
                "{\"ok\":true}".to_string()
            }
            "OPEN" => match unhex(rest).and_then(|b| String::from_utf8(b).ok()) {
                Some(p) => match Connection::open(Path::new(&p)) {
                    Ok(c) => {
                        db = c;
                        "{\"ok\":true}".to_string()
                    }
                    Err(e) => err_json(&e),
                },
                None => "{\"err\":\"runner: bad hex path\",\"code\":-1}".to_string(),
            },
            "E" | "Q" => match unhex(rest).and_then(|b| String::from_utf8(b).ok()) {
                Some(sql) => {
                    let result = panic::catch_unwind(AssertUnwindSafe(|| run(&mut db, op, &sql)));
                    match result {
                        Ok(r) => r,
                        Err(p) => {
                            let msg = p
                                .downcast_ref::<String>()
                                .cloned()
                                .or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string()))
                                .unwrap_or_else(|| "unknown panic".to_string());
                            db = fresh();
                            format!("{{\"panic\":\"{}\"}}", esc(&msg))
                        }
                    }
                }
                None => "{\"err\":\"runner: bad hex sql\",\"code\":-1}".to_string(),
            },
            _ => "{\"err\":\"runner: unknown command\",\"code\":-1}".to_string(),
        };
        let _ = writeln!(out, "{reply}");
        let _ = out.flush();
    }
}
