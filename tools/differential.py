#!/usr/bin/env python3
"""Write tests/differential_tests.nv from two Python Avro libraries.

The Apache Avro project's `avro` package, version 1.11.3, parses the
schemas, encodes the datums and writes the container files.
`fastavro`, version 1.12.2, answers schema resolution, which the first
library implements only in part.  Neither is in the standard library;
install both into a virtual environment and run the script with that
interpreter:

    python3 -m venv /tmp/avro-venv
    /tmp/avro-venv/bin/pip install avro==1.11.3 fastavro==1.12.2
    /tmp/avro-venv/bin/python tools/differential.py

Run from the package root.  The output is passed through `novo fmt`.

Four tables are written, each from a fixed seed:

1. canonical: a schema, the library's Parsing Canonical Form of it and
   its CRC-64-AVRO fingerprint.  A schema with a logical type on a
   primitive is left out of this table, because the library writes
   `{"type":"int"}` there and the specification's rule [PRIMITIVES]
   says `"int"`.
2. datums: a schema, a datum the library encoded, as hexadecimal, and
   the datum in Avro's JSON encoding.  Schemas with a logical type are
   left out, because the library represents their datums as Python
   decimals, dates and UUIDs rather than as the underlying type.
3. resolved: a writer's schema, a reader's schema, a datum encoded with
   the writer's, and the JSON encoding of what fastavro's resolving
   reader answered under the reader's schema.
4. files: an object container file the library wrote with the `null`
   codec, as hexadecimal, and its records in the JSON encoding.
"""
import io
import json
import math
import os
import random
import struct
import subprocess

import avro.datafile
import avro.io
import avro.schema
import fastavro

SEED = 20260928

PRIMITIVES = ['"null"', '"boolean"', '"int"', '"long"', '"float"', '"double"', '"bytes"',
              '"string"']

USER = json.dumps({
    "type": "record", "name": "User", "namespace": "com.example", "doc": "a user",
    "aliases": ["Person"],
    "fields": [
        {"name": "id", "type": "long"},
        {"name": "name", "type": "string", "doc": "the name"},
        {"name": "email", "type": ["null", "string"], "default": None},
        {"name": "tags", "type": {"type": "array", "items": "string"}},
        {"name": "props", "type": {"type": "map", "values": "int"}},
        {"name": "status", "type": {"type": "enum", "name": "Status",
                                    "symbols": ["ACTIVE", "DISABLED", "PENDING"]}},
        {"name": "hash", "type": {"type": "fixed", "name": "MD5", "namespace": "org.hash",
                                  "size": 16}},
        {"name": "address", "type": {"type": "record", "name": "Address", "fields": [
            {"name": "street", "type": "string"},
            {"name": "zip", "type": ["null", "int"]}]}},
        {"name": "previous", "type": ["null", "Address"], "default": None},
        {"name": "score", "type": "double", "order": "descending"},
        {"name": "ratio", "type": "float"},
        {"name": "flag", "type": "boolean", "order": "ignore"},
        {"name": "blob", "type": "bytes"},
    ]})

LONG_LIST = json.dumps({
    "type": "record", "name": "LongList", "aliases": ["LinkedLongs"],
    "fields": [{"name": "value", "type": "long"},
               {"name": "next", "type": ["null", "LongList"]}]})

SCHEMAS = PRIMITIVES + [
    USER,
    LONG_LIST,
    '["null","int","string","bytes"]',
    json.dumps({"type": "array", "items": {"type": "record", "name": "P", "fields": [
        {"name": "x", "type": "int"}, {"name": "y", "type": "int"}]}}),
    json.dumps({"type": "map", "values": {"type": "array", "items": "long"}}),
    json.dumps(["null", {"type": "record", "name": "a.A", "fields": [{"name": "n", "type": "int"}]},
                {"type": "record", "name": "b.A", "fields": [{"name": "s", "type": "string"}]}]),
    json.dumps({"type": "record", "name": "Outer", "namespace": "x.y", "fields": [
        {"name": "inner", "type": {"type": "record", "name": "Inner", "fields": [
            {"name": "e", "type": {"type": "enum", "name": "E", "namespace": "z",
                                   "symbols": ["A", "B"]}}]}},
        {"name": "again", "type": "Inner"},
        {"name": "e2", "type": "z.E"},
        {"name": "f", "type": {"type": "fixed", "name": "F", "size": 3}}]}),
    # The library writes a fixed used a second time in full in its
    # canonical form, where the specification writes its name, so this
    # one is left out of the canonical table.
    json.dumps({"type": "record", "name": "Pair", "fields": [
        {"name": "f", "type": {"type": "fixed", "name": "F", "size": 3}},
        {"name": "fs", "type": {"type": "array", "items": "F"}}]}),
    json.dumps({"type": "bytes", "logicalType": "decimal", "precision": 9, "scale": 2}),
    json.dumps({"type": "record", "name": "T", "fields": [
        {"name": "day", "type": {"type": "int", "logicalType": "date"}},
        {"name": "at", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "id", "type": {"type": "string", "logicalType": "uuid"}}]}),
    json.dumps({"type": "enum", "name": "Suit", "doc": "cards",
                "symbols": ["SPADES", "HEARTS", "DIAMONDS", "CLUBS"], "default": "SPADES"}),
    json.dumps({"type": "fixed", "name": "com.x.Sixteen", "size": 16}),
]

# Writer and reader pairs.  The reader's schema changes the writer's in
# the ways the specification allows.
RESOLVED = [
    ('"int"', '"long"'), ('"int"', '"float"'), ('"int"', '"double"'), ('"long"', '"double"'),
    ('"long"', '"float"'), ('"float"', '"double"'), ('"string"', '"bytes"'),
    ('"bytes"', '"string"'),
    ('"int"', '["null","long"]'), ('"string"', '["null","string"]'),
    ('["null","int"]', '["null","long","string"]'), ('["int","long"]', '"double"'),
    ('["null","string"]', '["string","null"]'),
    (json.dumps({"type": "array", "items": "int"}), json.dumps({"type": "array", "items": "long"})),
    (json.dumps({"type": "map", "values": "float"}), json.dumps({"type": "map", "values": "double"})),
    (json.dumps({"type": "enum", "name": "E", "symbols": ["A", "B", "C"]}),
     json.dumps({"type": "enum", "name": "E", "symbols": ["C", "B", "A", "D"]})),
    (json.dumps({"type": "enum", "name": "E", "symbols": ["A", "B", "C"]}),
     json.dumps({"type": "enum", "name": "E", "symbols": ["A", "B"], "default": "A"})),
    (json.dumps({"type": "record", "name": "R", "fields": [
        {"name": "a", "type": "int"}, {"name": "b", "type": "string"},
        {"name": "c", "type": {"type": "array", "items": "double"}}]}),
     json.dumps({"type": "record", "name": "R", "fields": [
         {"name": "c", "type": {"type": "array", "items": "double"}},
         {"name": "a", "type": "long"},
         {"name": "d", "type": ["null", "string"], "default": None},
         {"name": "e", "type": {"type": "record", "name": "S", "fields": [
             {"name": "x", "type": "int"}]}, "default": {"x": 7}},
         {"name": "f", "type": {"type": "array", "items": "int"}, "default": [1, 2]},
         {"name": "g", "type": "bytes", "default": "ÿ\u0001"}]})),
    (USER, json.dumps({
        "type": "record", "name": "User", "namespace": "com.example", "fields": [
            {"name": "id", "type": "long"},
            {"name": "status", "type": {"type": "enum", "name": "Status",
                                        "symbols": ["PENDING", "ACTIVE", "DISABLED", "GONE"]}},
            {"name": "address", "type": {"type": "record", "name": "Address", "fields": [
                {"name": "zip", "type": ["null", "long"]},
                {"name": "country", "type": "string", "default": "NO"}]}},
            {"name": "ratio", "type": "double"},
            {"name": "nick", "type": ["null", "string"], "default": None}]})),
    (LONG_LIST, json.dumps({
        "type": "record", "name": "LongList", "fields": [
            {"name": "next", "type": ["null", "LongList"]},
            {"name": "value", "type": "double"},
            {"name": "label", "type": "string", "default": "none"}]})),
]

def schema_of(text):
    return avro.schema.parse(text)


def gen(s, rng, depth):
    """A random datum of a schema, as the Python library represents it.

    A `bytes` or `fixed` value draws every byte from 0 to 255, so zero
    bytes pass through Avro's JSON encoding as `\\u0000`.
    """
    t = s.type
    if t == 'null':
        return None
    if t == 'boolean':
        return rng.random() < 0.5
    if t == 'int':
        return rng.choice([0, -1, 1, 63, -64, 64, 2 ** 31 - 1, -2 ** 31, rng.randint(-10 ** 6, 10 ** 6)])
    if t == 'long':
        return rng.choice([0, -1, 2 ** 63 - 1, -2 ** 63, rng.randint(-10 ** 12, 10 ** 12),
                           rng.randint(-10 ** 6, 10 ** 6)])
    if t == 'float':
        return struct.unpack('<f', struct.pack('<f', rng.uniform(-1000, 1000)))[0]
    if t == 'double':
        return rng.choice([0.0, -0.5, 1e20, rng.uniform(-1e6, 1e6)])
    if t == 'bytes':
        return bytes(rng.randrange(0, 256) for _ in range(rng.randint(0, 6)))
    if t == 'string':
        return ''.join(rng.choice(['a', 'b', 'é', '✓', ' ', 'Z', '"', '\\']) for _ in range(rng.randint(0, 6)))
    if t == 'fixed':
        return bytes(rng.randrange(0, 256) for _ in range(s.size))
    if t == 'enum':
        return rng.choice(s.symbols)
    if t == 'array':
        n = 0 if depth > 3 else rng.randint(0, 3)
        return [gen(s.items, rng, depth + 1) for _ in range(n)]
    if t == 'map':
        n = 0 if depth > 3 else rng.randint(0, 3)
        return {'k%d' % i: gen(s.values, rng, depth + 1) for i in range(n)}
    if t == 'union':
        choices = s.schemas
        if depth > 3:
            choices = [b for b in choices if b.type == 'null'] or choices
        return gen(rng.choice(choices), rng, depth + 1)
    if t in ('record', 'error'):
        return {f.name: gen(f.type, rng, depth + 1) for f in s.fields}
    raise ValueError(t)


def branch_name(b):
    return b.fullname if b.type in ('record', 'enum', 'fixed', 'error') else b.type


def to_json(s, d):
    """A datum as Avro's JSON encoding, as a Python object."""
    t = s.type
    if t in ('bytes', 'fixed'):
        if isinstance(d, str):
            # fastavro answers a `bytes` default as the default's own
            # string, whose characters are already the byte values.
            return d
        return ''.join(chr(x) for x in d)
    if t == 'array':
        return [to_json(s.items, x) for x in d]
    if t == 'map':
        return {k: to_json(s.values, v) for k, v in d.items()}
    if t in ('record', 'error'):
        return {f.name: to_json(f.type, d[f.name]) for f in s.fields}
    if t == 'union':
        for b in s.schemas:
            if avro.io.validate(b, d):
                if b.type == 'null':
                    return None
                return {branch_name(b): to_json(b, d)}
        raise ValueError('no branch')
    return d


def encode(s, d):
    buf = io.BytesIO()
    avro.io.DatumWriter(s).write(d, avro.io.BinaryEncoder(buf))
    return buf.getvalue()


def nv(text):
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$') + '"'


def dumps(obj):
    return json.dumps(obj, ensure_ascii=True, separators=(',', ':'))


def signed(n):
    return n - (1 << 64) if n >= 1 << 63 else n


def canonical_rows():
    rows = []
    for text in SCHEMAS:
        s = schema_of(text)
        if 'logicalType' in text or '"Pair"' in text:
            continue
        fp = int.from_bytes(s.fingerprint('CRC-64-AVRO'), 'little')
        rows.append('    (%s, %s, %d)' % (nv(text), nv(s.canonical_form), signed(fp)))
    return rows


def datum_rows(rng):
    rows = []
    for text in SCHEMAS:
        if 'logicalType' in text:
            continue
        s = schema_of(text)
        for _ in range(4):
            d = gen(s, rng, 0)
            rows.append('    (%s, %s, %s)' % (nv(text), nv(encode(s, d).hex()), nv(dumps(to_json(s, d)))))
    return rows


def resolved_rows(rng):
    rows = []
    for wtext, rtext in RESOLVED:
        w = schema_of(wtext)
        r = schema_of(rtext)
        for _ in range(4):
            d = gen(w, rng, 0)
            if w.type in ('int', 'long') and r.type == 'float':
                d = rng.randint(-2 ** 20, 2 ** 20)
            if w.type == 'bytes' and r.type == 'string':
                d = gen(r, rng, 0).encode('utf-8')
            data = encode(w, d)
            got = fastavro.schemaless_reader(
                io.BytesIO(data), fastavro.parse_schema(json.loads(wtext), named_schemas={}),
                fastavro.parse_schema(json.loads(rtext), named_schemas={}))
            rows.append('    (%s, %s, %s, %s)' % (nv(wtext), nv(rtext), nv(data.hex()),
                                                  nv(dumps(to_json(r, got)))))
    return rows


def file_rows(rng):
    rows = []
    for text in [USER, LONG_LIST, '"string"']:
        s = schema_of(text)
        for n in (0, 3, 40):
            buf = io.BytesIO()
            w = avro.datafile.DataFileWriter(buf, avro.io.DatumWriter(), s, codec='null')
            records = [gen(s, rng, 0) for _ in range(n)]
            for i, d in enumerate(records):
                w.append(d)
                if i % 7 == 6:
                    # End the block, so a file holds several.
                    w.sync()
            w.flush()
            data = buf.getvalue()
            w.close()
            listed = '[' + ', '.join(nv(dumps(to_json(s, d))) for d in records) + ']'
            rows.append('    (%s, %s)' % (nv(data.hex()), listed))
    return rows


def main():
    rng = random.Random(SEED)
    canon = canonical_rows()
    datums = datum_rows(rng)
    resolved = resolved_rows(rng)
    files = file_rows(rng)
    text = HEADER + '\n// The canonical cases: schema, canonical form, fingerprint.\n'
    text += 'fn canonical_rows() -> [(Str, Str, Int)]\n    [' + ',\n'.join(canon).lstrip() + ']\n'
    text += '\n// The datums: schema, encoding in hexadecimal, JSON encoding.\n'
    text += 'fn datum_rows() -> [(Str, Str, Str)]\n    [' + ',\n'.join(datums).lstrip() + ']\n'
    text += ('\n// The resolved datums: writer, reader, encoding under the writer,\n'
             '// JSON encoding under the reader.\n')
    text += 'fn resolved_rows() -> [(Str, Str, Str, Str)]\n    [' + ',\n'.join(resolved).lstrip() + ']\n'
    text += '\n// The container files: the file in hexadecimal, and its records.\n'
    text += 'fn file_rows() -> [(Str, [Str])]\n    [' + ',\n'.join(files).lstrip() + ']\n'
    text += FOOTER
    path = os.path.join('tests', 'differential_tests.nv')
    open(path, 'w').write(text)
    subprocess.run(['novo', 'fmt', path], check=True)


HEADER = '''// differential_tests.nv — this package against the Apache Avro Python
// library, version 1.11.3, which answers the same questions
// independently.
//
// Written by tools/differential.py; do not edit by hand.  JSON is
// compared as JSON values, so `1e20` and `1e+20` are the same number.

use std.test
use std.bytes
use std.json
use avrobinary
use avrocodec
use avrofile
use avrofp
use avroresolve
use avroschema
use avrovalue
'''

FOOTER = '''
// Whether two JSON texts denote the same value.
fn same_json(a: Str, b: Str) -> Bool
    match (json.parse(a), json.parse(b))
        (Some(x), Some(y)) => json.equals(x, y)
        _                  => false

// A buffer from hexadecimal.
fn unhex(text: Str) -> Bytes
    bytes.from_hex(text) ?? bytes.zeros(0)

@test
fn test_the_canonical_form_and_the_fingerprint_agree() [io]
    for (text, canonical, fp) in canonical_rows()
        test.case(text)
        match avroschema.parse(text)
            Err(e) => test.fail(e.message())
            Ok(s)  =>
                test.assert_eq_str(avroschema.canonical_form(s), canonical)
                test.assert_eq(avrofp.fingerprint(s), fp)
                test.assert_eq(avrofp.rabin(canonical), fp)

@test
fn test_every_datum_decodes_and_encodes_back() [io]
    for (text, hex, want) in datum_rows()
        test.case("${text} ${hex}")
        match avroschema.parse(text)
            Err(e) => test.fail(e.message())
            Ok(s)  =>
                match avrobinary.decode(unhex(hex), 0, s, avrobinary.default_limits())
                    Err(e) => test.fail(e.message())
                    Ok(v)  =>
                        match avrovalue.to_json(v, s)
                            Err(e) => test.fail(e.message())
                            Ok(j)  => test.assert_true(same_json(j, want), "${j} is not ${want}")
                        match avrobinary.encode(v, s)
                            Err(e) => test.fail(e.message())
                            Ok(b)  => test.assert_eq_str(bytes.to_hex(b), hex)
                match avrovalue.from_json(want, s)
                    Err(e) => test.fail(e.message())
                    Ok(v)  =>
                        match avrobinary.encode(v, s)
                            Err(e) => test.fail(e.message())
                            Ok(b)  => test.assert_eq_str(bytes.to_hex(b), hex)
                test.assert_eq(avrobinary.skip(unhex(hex), avrobinary.cursor(0), s,
                                               avrobinary.default_limits()).at, str.len(hex) / 2)

@test
fn test_every_resolved_datum_reads_as_the_library_reads_it() [io]
    for (wtext, rtext, hex, want) in resolved_rows()
        test.case("${wtext} as ${rtext}: ${hex}")
        match (avroschema.parse(wtext), avroschema.parse(rtext))
            (Ok(w), Ok(r)) =>
                match avroresolve.resolve(w, r)
                    Err(e) => test.fail(e.message())
                    Ok(p)  =>
                        match avroresolve.decode(unhex(hex), 0, p, avrobinary.default_limits())
                            Err(e) => test.fail(e.message())
                            Ok(v)  =>
                                match avrovalue.to_json(v, r)
                                    Err(e) => test.fail(e.message())
                                    Ok(j)  => test.assert_true(same_json(j, want), "${j} is not ${want}")
            _              => test.fail("both schemas parse")

@test
fn test_every_container_file_reads_record_for_record() [io]
    for (hex, want) in file_rows()
        test.case("a file of ${list.len(want)} records")
        let src = unhex(hex)
        match avrofile.read_header(src)
            Err(e) => test.fail(e.message())
            Ok(h)  =>
                match avrofile.read_all(src, avrocodec.only_null(), -1)
                    Err(e) => test.fail(e.message())
                    Ok(vs) =>
                        test.assert_eq(list.len(vs), list.len(want))
                        for i in 0..list.len(vs)
                            match avrovalue.to_json(vs[i], h.schema)
                                Err(e) => test.fail(e.message())
                                Ok(j)  => test.assert_true(same_json(j, want[i]), "${j} is not ${want[i]}")
'''

if __name__ == '__main__':
    main()
