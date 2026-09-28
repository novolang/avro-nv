# avro-nv

Apache Avro is a data serialization system, specified by
[the Avro 1.11.1 specification](https://avro.apache.org/docs/1.11.1/specification/).
Data is written with a schema, and read with a schema that may be a different
one. This package reads and writes it in novo-lang, and performs no input or
output itself.

## What Avro is

An Avro **schema** is JSON. It names one of eight *primitive* types — null,
boolean, int, long, float, double, bytes, string — or one of six *complex*
ones: record, enum, array, map, union, fixed. Three of the complex types are
*named*: record, enum and fixed carry a name and a namespace, and their full
name is how two schemas are matched.

Avro's **binary encoding has no markers in it at all.** A record is its fields'
encodings concatenated: no field tag, no length, no terminator, no padding. An
`int` and a `long` are zigzagged and then written seven bits per byte. A
`bytes` or a `string` is a length and then its bytes. An array or a map is a
count, that many items, and a count of zero to end. A union is a branch index
and then that branch. That is the whole format.

That absence of markers is why Avro is small, and it is the single most
important fact about reading it: a decoder using a schema that does not match
the writer's does not fail. It reads the next field's bytes as this field's,
produces a plausible wrong value, and carries on.

**Schema resolution** is what the format offers instead. A reader has its own
schema; the writer's arrives with the data. The specification gives rules for
when the two are compatible — a field the writer has and the reader does not is
skipped, a field the reader has and the writer does not is filled from its
default, an `int` promotes to a `long`, names may be matched through aliases —
and a pair that does not satisfy them is a mismatch that must be caught before
decoding, because nothing will catch it afterwards.

An **object container file** puts a schema in its header and then blocks of
records. Every block ends with a sixteen-byte random *sync marker*, so a reader
handed the middle of a five-gigabyte file can scan forward to the next block
boundary and read from there. That is what made Avro the format for bulk data.

A **single-object encoding** is for the other case: a message queue, where each
record is its own message and a schema cannot be repeated. It is two marker
bytes, an eight-byte *fingerprint* of the schema, and then the record.

| Value | Size |
| --- | --- |
| Primitive types | 8 |
| Complex types | 6, of which 3 are named |
| `int`, `long` | zigzag, then 7 bits per byte, 1 to 10 bytes |
| `float`, `double` | 4 and 8 bytes, little-endian IEEE 754 |
| `null` | 0 bytes |
| Container file magic | 4 bytes: `Obj` and version 1 |
| Container file sync marker | 16 bytes, random, at the end of every block |
| Single-object marker | 2 bytes: `C3 01` |
| Single-object fingerprint | 8 bytes, CRC-64-AVRO, little-endian |
| Type promotions | 6, one-directional; plus string ↔ bytes both ways |

## Install

```
novo pkg add avro-nv
```

## Example

```novo
use avroresolve
use avroschema

fn main() [io]
    // A reader's schema and a writer's, checked against each other
    // before any data is decoded.
    match avroschema.parse("\"int\"")
        Err(e) => println(e.message())
        Ok(writer) =>
            match avroschema.parse("\"long\"")
                Err(e) => println(e.message())
                Ok(reader) =>
                    // int promotes to long, so this resolves.
                    match avroresolve.resolve(writer, reader)
                        Err(e) => println(e.message())
                        Ok(plan) => println(avroresolve.describe(plan))
```

The program prints `` `long` is promoted from int to long. ``

## What the package contains

| Module | Contents |
| --- | --- |
| `avroschema` | The schema language: the fourteen types, the naming rules, the union rules, field defaults, and the Parsing Canonical Form. |
| `avroresolve` | Schema resolution as a plan: what to do with every field, symbol and branch, decided once. |
| `avrobinary` | The binary encoding both ways, over a cursor and a set of bounds the caller supplies. |
| `avrovalue` | The value a datum decodes to, the two JSON encodings, and the specification's sort order. |
| `avrological` | The logical types, including the rule that an unusable annotation is ignored. |
| `avrofile` | The object container file: the header, blocks, the sync marker, and a writer. |
| `avrocodec` | A codec as a value: a name and named functions a caller supplies. `null` is built in. |
| `avrofp` | The CRC-64-AVRO Rabin fingerprint, and the single-object encoding. |
| `avroerror` | `AvroFault` with the schema path or the block and offset it happened at, and the four questions `is_corrupt`, `is_incomplete`, `is_schema_error` and `is_unsupported`. |

No function in this package opens a file, reads a clock, generates a random
number or waits for anything.

## How to choose an entry point

**You have a container file in memory and want its records:
`avrofile.read_all`.** It reads the header, checks the codec, and walks every
block.

**You want the blocks one at a time: `avrofile.reader`, then
`avrofile.read_block` or `avrofile.skip_block` until `avrofile.at_end`.**

**You want the file's own schema first: `avrofile.read_header`.** The header
carries it, and `avrofile.readable_with` says whether the codecs you supplied
can read the blocks.

**You are reading with your own schema: `avrofile.reader_with_schema`.**
Resolution runs once, at open, and a file that cannot be read through your
schema is refused there with the rule that failed named.

**You are checking whether a schema change is safe: `avroresolve.resolve` and
`avroresolve.describe`.** No data needed. This is the call a schema review
makes.

**You are reading one datum out of a message: `avrofp.read_single_object_prefix`
and `avrobinary.decode`.** The first says which schema, the second reads the
datum.

**You are writing a container file: `avrofile.writer`.** You supply the
sixteen-byte sync marker; see rule 5.

**You want the low-level encoding: `avrobinary`.** `read_long`, `write_long`,
`skip` and the cursor.

## The rules a user needs

1. **A decoder with the wrong schema does not fail; it produces wrong values.**
   The binary encoding has no field tags, no lengths on a record and no
   terminators, so there is nothing to notice a mismatch with. Every other rule
   here follows from this one.
2. **So resolution is a separate check, made once, before any data is read.**
   `avroresolve.resolve` either answers a plan or names the specification rule
   that failed. `avrofile.reader_with_schema` runs it at open time. A decoder
   that resolved as it went would already have produced wrong values by the
   time it noticed. The specification reports a writer's union branch or enum
   symbol that the reader cannot take only when such a value is read; this
   package refuses the pair of schemas instead.
3. **Aliases belong to the reader.** A reader that renamed a record, enum,
   fixed or field lists the old name in `aliases`, and the writer's data is
   read under the new name (specification section "Aliases"). An alias on the
   writer's schema does nothing.
4. **Promotions go one way only.** `int` widens to `long`, `float` or `double`;
   `long` to `float` or `double`; `float` to `double`; and `string` and `bytes`
   convert both ways because their encodings are identical. Nothing narrows —
   Avro will not truncate a value silently.
5. **The container file's sync marker must be random, and this package cannot
   make one.** It is sixteen bytes at the end of every block, and a reader
   splitting a large file scans for it — so a marker that appeared inside
   somebody's data would split a file in the wrong place. This package has no
   `[rand]`, so `avrofile.writer` takes the marker and the caller spends its own
   randomness where it is visible.
6. **A compression codec is a value you supply, not a dependency.**
   `avro.codec` is a string in a file's metadata and the specification says the
   set is open. `avrocodec.reader_codec` takes a name and two named functions:
   one that answers the decompressed size, one that decompresses. `null` is
   built in. A file naming a codec you did not supply is
   `AvroUnsupportedCodec`, which is not a corrupt file — ask
   `avrofile.readable_with` over the header, at open time.
7. **Avro's `snappy` is not plain Snappy.** It is a Snappy block with a
   four-byte big-endian CRC-32C of the *uncompressed* data appended, which the
   Snappy format itself does not have. And Avro's `deflate` is raw DEFLATE with
   no zlib wrapper and no gzip header.
8. **Decoding is bounded, and bounded by default.** A `bytes` length is a
   varint, so five bytes of input can declare a two-gigabyte string.
   `avrobinary.default_limits()` allows 64 MiB per value, 16 million items per
   block and 64 levels of nesting; `avrobinary.no_limits()` is there for a
   caller decoding what it wrote.
9. **An unusable logical-type annotation is ignored, not refused.** The
   specification requires it: the implementation uses the underlying type and
   carries on, so a reader that has never heard of `timestamp-millis` still
   reads the field as a `long`. `avrological.check` is the separate call that
   *tells* you an annotation you wrote is being ignored.
10. **A `timestamp` and a `local-timestamp` are not the same thing, and the
   bytes cannot tell you which.** Both are a `long` of the same magnitude; one
   is an instant in UTC and the other is a wall clock reading with no zone.
   `avrological.is_instant` is the question.
11. **A decimal is two's complement and big-endian; a duration is unsigned and
    little-endian.** A reader that treated a decimal's bytes as unsigned reads
    every negative number wrong. `duration` is the only little-endian logical
    type in the specification.
12. **CRC-64-AVRO is not a standard CRC-64.** It is a 64-bit Rabin fingerprint
    whose polynomial *and* initial value are `0xC15D213AA4D7A795`. A port that
    reached for CRC-64/ECMA-182 or CRC-64/XZ would produce fingerprints no
    other Avro reader recognises. The specification's own check value —
    `0x63DD24E7CC258F8A` for the canonical form `"null"` — is asserted in
    `tests/avroresolve_tests.nv`.
13. **A union's branch order is part of its meaning.** A branch is encoded as
    its index, so adding a branch to the front of a reader's union changes what
    every old record reads as. Adding one to the back does not.
14. **Every public type, variant and module name in this package starts `Avro`
    or `avro`.** Type and variant names are unique across a whole program,
    dependencies included, so two packages that both declared `Schema` could not
    be used together. `Schema`, `Field`, `Record`, `Codec` and `Fault` are all
    names another package will want, so this one takes none of them.

## What is not included

- **Code generation.** No `.avsc` compiler, no generated record types. A schema
  is a value at run time and a datum is an `AvroValue`. A generator is a
  separate program that can be written on top of `avroschema`.
- **Compression codecs.** See rule 6.
- **The RPC protocol.** Avro defines a protocol — messages, handshakes,
  transports — beside the data format. It is `[net]` work, this package is
  `core`, and it belongs in a package on top of this one.
- **A schema registry client.** Fetching a schema by fingerprint is `[net]`.
  `avrofp.schema_for` takes the schemas a caller already has, and
  `AvroUnknownFingerprint` is the signal that turns into "fetch this one".
- **Big decimals.** `avrological.decimal_unscaled` answers a 64-bit integer and
  refuses bytes that hold more, rather than truncating. A `decimal` with a
  precision above nineteen digits needs a big integer this package does not
  carry.
- **Avro's IDL (`.avdl`).** A second surface syntax for the same schemas.

## Related packages

- [parquet-nv](https://novo-lang.org/packages/parquet-nv) is the columnar
  format for the same data. Its `PqDecompressor` is the same
  codec-as-named-functions shape this package's `AvroCodec` uses, so a program
  reading both wires one pair of functions to both.
- [flate-nv](https://novo-lang.org/packages/flate-nv),
  [snappy-nv](https://novo-lang.org/packages/snappy-nv) and
  [zstd-nv](https://novo-lang.org/packages/zstd-nv) are what a caller wires in
  for the three named codecs.
- [protobuf-nv](https://novo-lang.org/packages/protobuf-nv) is the other
  schema-first binary encoding. Its wire format carries field tags, which is
  the design decision Avro made the other way.
- [crypto-nv](https://novo-lang.org/packages/crypto-nv) supplies the MD5 and
  SHA-256 a caller hands to `avrofp.wide_fingerprint`.

## The reference implementations

[apache-avro](https://github.com/apache/avro) (the Rust crate) and
[fastavro](https://github.com/fastavro/fastavro), with
[the Avro 1.11.1 specification](https://avro.apache.org/docs/1.11.1/specification/)
as the format document. This package keeps the specification's own names where
they are good — `avro.schema`, `avro.codec`, the Parsing Canonical Form, the
four resolution actions — so a reader with that page open recognises what they
are.

## Tests

```bash
novo test tests/avroschema_tests.nv         # the fourteen types, names, defaults, logical types
novo test tests/avroschemaedge_tests.nv     # every refusal of the parser, and the written form
novo test tests/avrobinary_tests.nv         # zigzag varints, blocks, the value type, the limits
novo test tests/avrovalueedge_tests.nv      # value checks, both JSON forms, sort order, damaged input
novo test tests/avroresolve_tests.nv        # resolution, codecs, the container file, fingerprints
novo test tests/avroresolveedge_tests.nv    # every resolution rule, describe, logical types
novo test tests/avrofileedge_tests.nv       # files written and read back, damaged files, codecs
novo test tests/avroerror_tests.nv          # every fault kind, its name and its sentence
novo test tests/differential_tests.nv       # against the Python Avro libraries
bash tests/coverage.sh                      # line coverage over src/, merged across the suites
```

The differential suite is written by `tools/differential.py` from two
independent implementations: the Apache Avro project's Python library,
version 1.11.3, and fastavro, version 1.12.2. It checks the Parsing Canonical
Form and the CRC-64-AVRO fingerprint of 17 schemas, the binary encoding of
72 datums both ways, 80 datums read through a different reader schema, and 9
container files read record for record. A `bytes` or `fixed` datum draws every
byte value from 0 to 255, zero included, so the JSON encoding is checked with
`\u0000` in its strings.

The specification's own check values are asserted in
`tests/avroresolve_tests.nv`: `0x63DD24E7CC258F8A` for `"null"` and
`0x8F014872634503C7` for `"string"`. The CRC-32C of Avro's `snappy` framing is
checked against the RFC 3720 check value `E3069283` for `123456789`.

## Licence

Apache-2.0. See `LICENSE`.
