# Reflection across package metadata

`model` exports an annotated record and a generic reflection function.
`custom` implements both `serialize` traits for a small comma-separated format,
without depending on JSON. `app` calls all three formats on types declared in
different packages, exercising retained templates and private import aliases.

From `app`, run the newly built compiler:

```sh
../../../../target/release/encore run --profile dev --jobs 3
```

Run again to exercise cached package metadata. Exit code zero means success.

From the repository root, `python3 tests/fixtures/reflection_codecs/check.py`
also checks a warm cache and invalidation after a template body changes. It
temporarily changes the model helper, checks the unchanged app sees that change,
restores the source in a `finally` block, and verifies the original result.
An optional first argument selects another compiler executable.
