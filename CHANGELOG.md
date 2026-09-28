# Changelog

All notable changes to avro-nv are recorded here. The format is
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
package follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with the pre-1.0 rule that a breaking change bumps the MINOR number.

## [0.1.0] — 2026-09-28

The first implementation of the interface published as 0.0.1.

### Added

- `avroschema` parses a schema with `std.json` and checks every naming,
  union and default rule at parse.  A use of a named type after its
  definition is a copy of the definition; a use inside its own
  definition, as in a linked list, is a reference that every walk looks
  up in the enclosing definition.  `to_json` writes a schema back with
  its docs, aliases, defaults and logical types, and `canonical_form`
  follows the specification's Parsing Canonical Form.
- `avrobinary` decodes and encodes every type.  A float is rounded to 32
  bits and its bit pattern kept through NaN, the infinities and the
  subnormals.  `decode`, `skip` and `encoded_bytes` share one walk.
- `avroresolve` builds the plan for every rule of the specification's
  section "Schema Resolution", including a recursive record, and
  `describe` puts it in sentences.
- `avrovalue` reads and writes Avro's JSON encoding and the field
  default form, and compares values in the specification's sort order.
- `avrofile` reads and writes container files; `avrocodec` checks and
  writes the CRC-32C trailer of Avro's `snappy` framing; `avrofp`
  computes CRC-64-AVRO.
- `tests/differential_tests.nv`, written by `tools/differential.py`,
  checks canonical forms, fingerprints, datums, resolved datums and
  container files against the Apache Avro Python library 1.11.3 and
  fastavro 1.12.2.

### Changed

These break code written against 0.0.x.

- `AvroSchema` has a new field, `is_reference`, true for a use of a
  named type inside its own definition.
- `AvroFaultKind` has a new variant, `AvroChecksumMismatch(codec)`, for
  a `snappy` block whose CRC-32C does not match.  `is_corrupt` answers
  true for it.
- `avrobinary.write_long` and `avrobinary.encode_into` take their
  buffer as `var dst: Bytes`, since they write into it.
- Aliases are the reader's, as the specification's section "Aliases"
  says: `avroresolve.names_match` matches the writer's full name
  against the reader's name and aliases.  The interface's comments had
  the direction the other way.
- `avroresolve.resolve` refuses a writer's union branch or enum symbol
  the reader cannot take, where the specification reports it only when
  such a value is read.  A plan never fails part of the way through a
  file.
- `AvroResolution.nested` holds one plan per read or promoted field,
  per writer branch of a union, for the branch of a reader's union, or
  for the items of an array or a map.
- `avrofile.next_block` answers `AvroTruncated` at the end of the file.
  `avrofile.at_end`, new, asks first.
- `avrobinary.AVRO_CURSOR_BAD_INDEX`, new, is the cursor code for a
  union branch or enum symbol index outside its schema.
- `avrological.check` answers `AvroNotLogical` for a schema with no
  annotation, and `AvroBadLogicalType` for an annotation this package
  does not know as well as one that does not fit.  `fits` accepts a
  `decimal` scale of 0.

## [0.0.1] — 2026-09-17

**The interface, published before anyone implements it.** Every public
type and function carries its full signature, its effect row and its
doc comment; every body is `todo()`; the release is recorded
`implemented = false`.

### Added

- `avroresolve` — the load-bearing interface, and the reason the
  package is shaped the way it is. Avro's binary encoding has no
  markers, so a decoder using the wrong schema does not fail: it reads
  the next field's bytes as this field's and produces a plausible wrong
  value. Resolution is therefore a check over two schemas made ONCE,
  before any data is read, that either answers a PLAN — read, skip,
  default or promote, per field, with enum and union index maps and the
  defaults already decoded — or names the specification rule that
  failed. `avrofile.reader_with_schema` runs it at open time, and
  `describe` puts the plan in the words a schema review is read in.
- `avroschema` — the fourteen types, the union rules checked at parse
  (no union inside a union, no repeated type), field defaults checked
  at parse, and `full_name_in`: the namespace rule everybody gets
  wrong, written once. `canonical_form` is what every fingerprint is
  taken over.
- `avrobinary`, `avrovalue` — the encoding and the value. The value
  type is this package's own rather than a JSON value, because a JSON
  value throws away six distinctions Avro makes: bytes versus string,
  int versus long, float versus double, an enum's index, a fixed's
  identity, and WHICH BRANCH a union value came from. Decoding is
  bounded by default, because a `bytes` length is a varint and five
  bytes can declare two gigabytes.
- `avrofile` — the container file. The sync marker is the caller's:
  sixteen random bytes are what let a reader split a five-gigabyte file
  at an arbitrary offset, `core` has no `[rand]`, and a hard-coded
  marker would one day appear inside somebody's data.
- `avrocodec` — **the decision this release is asked to make.** The
  codecs are VALUES a caller hands in — a name and named functions —
  and not dependencies. novo's manifest has no optional dependencies,
  so a dependency is a hard one in every consumer's closure, and
  flate-nv, snappy-nv and zstd-nv are all INTERFACE releases today: a
  consumer reading an uncompressed Avro file would resolve, download
  and build three packages it cannot call. `avro.codec` is also an open
  set by specification, so a closed enum would refuse a file a newer
  writer produced. parquet-nv's `PqDecompressor` is the same shape on
  this registry, so a program reading Parquet and Avro wires one pair
  of functions to both. `null` is built in, because it is not
  compression.
- `avrological` — the logical types, with the specification's rule that
  an unusable annotation is IGNORED rather than refused, and `check` as
  the separate call that tells a schema author it is being ignored.
  `is_instant` separates the three `timestamp-*` from the three
  `local-timestamp-*`, which the bytes cannot.
- `avrofp` — CRC-64-AVRO, which is NOT a standard CRC-64: its
  polynomial and its initial value are both `0xC15D213AA4D7A795`, and a
  port that reached for CRC-64/ECMA-182 would produce fingerprints no
  other Avro reader recognises. The specification's two worked check
  values are asserted.
- `avroerror` — twenty-five fault kinds and FOUR predicates rather than
  three: `is_schema_error` separates a developer's problem from a
  file's, and `is_unsupported` separates a build's.

### Known

- `novo test` is red, and that is the release's expected state: every
  assertion in the three API suites reaches `not implemented:
  avro-nv.<module>.<fn>`.
- **Four `@value` structs answer a flag rather than a `Result`** —
  `AvroCursor`, `AvroLongRead`, `AvroBlockCount` and the step types
  built on them. A `@value` struct cannot be a `Result` payload in v1,
  and a cursor that boxed itself would allocate once per FIELD of every
  record. `avrobinary.fault_of` turns the flag into the fault the rest
  of the package speaks.
- **No big decimals.** `avrological.decimal_unscaled` answers a 64-bit
  integer and refuses bytes that hold more rather than truncating. A
  `decimal` above nineteen digits of precision needs a big integer this
  package does not carry, and the README says so.
