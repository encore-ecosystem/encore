# toml

Parses the manifest subset used by Encore: sections, strings, integers, booleans
and arrays of strings. Basic strings decode quote, backslash, control-character
and Unicode escapes (`\uXXXX` and `\UXXXXXXXX`). Single-quoted strings preserve
backslashes. Quoted delimiters and trailing comments are handled without
including the comment in the string value. String scanning uses UTF-8 byte
coordinates consistently.
