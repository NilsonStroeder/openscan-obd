# Project guidance

## Product scope

This repository is a general, extensible automotive diagnostic scanner. It is
not a Nissan-only or CVT-only product. The Nissan Sentra B16 2010 is the
current test vehicle; CVT work is one research track, not the project's
primary scope.

## Engineering guidance

- Prefer standards-based, reusable behavior for OBD-II and supported
  diagnostic protocols.
- Keep manufacturer/model-specific addresses, services, DIDs, LIDs, codecs,
  and assumptions in explicit profiles or modules rather than in generic
  scanner flows.
- Do not imply broad vehicle compatibility based only on protocol support or a
  single test vehicle. Record vehicle, ECU, adapter, and validation evidence.
- Preserve raw response bytes whenever a value's meaning, length, or scaling is
  not confirmed. Mark hypotheses as unverified.
- Keep diagnostic/read-only behavior distinct from programming, writes, resets,
  and active routines. Do not add those operations without explicit scope and
  safety review.
- Add or update offline tests for protocol parsing and decoders; do not require
  a real vehicle for unit tests.
- Update README and related docs when capabilities or project scope changes.

## Current implementation note

The generic OBD-II layer coexists with a currently Nissan-specific module
catalog and KWP research workflow. Do not describe that catalog as universal
ECU discovery.
