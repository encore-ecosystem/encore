# Language bootstrap staging

The published compiler selected by Native CI must be able to build stage1 from
this checkout. Stage2 and stage3 then use isolated caches and must be identical.

Release 0.1.15 is the bridge from the published 0.1.14 compiler. It implements
literal parameter defaults, named arguments, From/Into and resolution of both
one- and two-argument arithmetic operator contracts. Its compiler and SDK sources
retain syntax and operator declarations accepted by 0.1.14. Integration fixtures
exercise the new syntax and preview the next SDK contract.

Release 0.1.16 switches arithmetic, bitwise and shift traits to two mandatory
arguments, removes implicit numeric operator casts, and can adopt the new call
syntax in compiler and SDK sources. Its minimum published seed is 0.1.15.

`scripts/bootstrap-compatibility.json` records each checkout's minimum seed.
Native CI rejects an older seed before starting native bootstrap jobs. Publish
and verify the complete six-platform bridge release before promoting the next
stage. A successful stage1 build alone does not replace full library/compiler
checks or stage2/stage3 convergence.
