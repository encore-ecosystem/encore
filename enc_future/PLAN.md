# enc_future Self-Hosted Plan

## Цель
Довести `enc_future` до состояния, где он:
- сам парсит/проверяет/понижает Encore-код,
- сам генерирует `eHIR -> LLVM IR -> object/lib/executable`,
- сам компилирует себя (bootstrap),
- и после этого Python-версия компилятора больше не нужна в рабочем пайплайне.

## Текущее состояние (baseline)
- Есть рабочий self-hosted CLI и lexer.
- В `build` есть bridge на host (Python) для backend-этапа.
- Полного self-hosted frontend/middle-end/backend пайплайна пока нет.

## Definition of Done (финальный критерий)
Python-реализацию можно отключать только если одновременно выполнено:
- `enc_future` собирает весь `enc_future/examples` без host-bridge.
- `enc_future` собирает `enc_future` самим собой (минимум 2 итерации bootstrap).
- Для smoke/regression набора артефакты и поведение совпадают с эталоном (IR/exit code/диагностика ошибок в допустимых рамках).
- CI зелёный только на self-hosted пути.

---

## Stage 0: Freeze Contracts
- [x] Зафиксировать стабильный контракт build pipeline: `manifest -> frontend -> eHIR -> backend -> artifacts`.
- [x] Зафиксировать target-типы: `executable`, `static_lib`, `object`, `dynamic_lib`.
- [x] Зафиксировать layout артефактов (`target/<profile>/{llvm,object,...}`) и формат кэша.
- [x] Зафиксировать ABI/FFI runtime-функций (минимум: string/io/os/file/process).

Progress:
- [x] `build` стабильно работает по контракту: manifest -> frontend-pass -> payload -> backend.
- [x] Target normalization и artifact path policy уже используются в `modes/manifest` и `modes/build`.
- [x] Runtime ABI закрыт для `string/io/os` и процесса (`run_command`) на текущем этапе.
- [x] Инвалидация stale compiled-refrains выполняется через `COMPILER_VERSION` (был bump после fix-ов frontend/backend совместимости).

### DoD
- Документированы и не плавают контракты входа/выхода между стадиями.

## Stage 1: Self-Hosted Frontend (до eHIR)
- [x] Lexer parity с текущими токенами и суффиксами литералов.
- [ ] Parser: directives, types/generics, expressions, statements, path/import grammar, `unsafe`.
- [ ] Name resolution/import graph (включая `refrain::` и re-export/cimp поведение).
- [ ] Type inference + type checker (let/fn return/match/block expr/enum payload/struct init).
- [ ] Диагностика: человекочитаемые ошибки с позицией.

Progress:
- [x] Добавлен модуль `frontend/parser.enq` и подключен в `frontend/mod.enq`.
- [x] В `modes/build` добавлен parser-pass после lexer-pass.
- [x] Реализована стабильная потоковая parser-валидация (`UNKNOWN` + баланс `()[]{}`) с ошибкой и позицией.
- [x] Lexer обновлен для чисел с `_`-separator и суффиксами (`_u32`, `_f32`, `usize/isize`-style suffix tokens).
- [x] Parser покрывает `unsafe fn` на top-level (в дополнение к `extern unsafe fn`).
- [x] Seed parser/translator пропускает `enc_future/src/frontend/*` (починены expression-block `if/match`, chain field access `a.b.c`).
- [x] Self-hosted smoke (`examples/while`, `examples/refrains`) проходит parser-pass стабильно.
- [x] `parse()` возвращает структурированный `ParseOutcome::Success(ParsedModule)` с метаданными по top-level directives.
- [x] `build` печатает parser outline top-level директив (импорт/struct/enum/trait/impl/fn/extern/unsafe).
- [x] Self-hosted parser поддерживает grouped imports `import a::{b, c::D, e::*}` и trailing-comma внутри группы.
- [x] Для `struct` включён grammar-level разбор тела: поля `name: Type` (newline/comma-стиль), с проверкой баланса generic/paren/square в типах полей.
- [x] Для `enum` включён grammar-level разбор вариантов: `Variant`, `Variant(T)`, список вариантов (newline/comma-style) и payload в `(...)`.
- [x] В self-hosted parser добавлена поддержка C-like enum payload: `Variant { field: Type, ... }`.
- [x] `build` выводит позицию parser-ошибки (`line:column`) в self-hosted режиме.
- [x] Сигнатуры `trait fn`/`extern fn` разведены по границам парсинга (trait-метод завершается на `}` в trait-body, extern остаётся top-level-only).
- [x] `impl` теперь требует явное тело `{ ... }` (раньше мог молча пройти без блока).
- [x] Убраны прямые `enum ==` сравнения в parser-runtime-пути (заменены на `match`-helper), чтобы backend не падал на `icmp` для enum.
- [x] Host Python parser в bridge-пути поддерживает trailing-comma в import group.
- [x] Host Python parser/translator в bridge-пути поддерживает enum payload с composite-структурами (tuple arity > 1 и единичный composite-аргумент).
- [x] Host Python translator в bridge-пути нормализует top-level `unit/tuple struct` в C-like форму (для совместимости self-hosted parser smoke-кейсов).
- [x] В self-hosted parser добавлена statement-level валидация тел функций/блоков (`let/ret/if/elif/else/while/loop/do-while/match/unsafe` + assignment/expression statements), вместо прежнего "brace-only" прохода.
- [x] В self-hosted parser добавлен grammar-level разбор `for` statement (`for <binding> in <expr> { ... }`) с явной диагностикой на некорректный `in`.
- [x] В self-hosted parser добавлена контекстная валидация `break/continue`: эти statements теперь разрешены только внутри loop-body (`while/for/loop/do-while`).
- [x] Host Python parser синхронизирован по loop-control: `break/continue` вне loop-body теперь также валятся на parser-этапе (включая вложенные expression-block/unsafe/match contexts).
- [x] Host Python parser синхронизирован по `unsafe fn`: поддержаны top-level `unsafe fn` и `extern unsafe fn`.
- [x] В self-hosted parser `match`-arms расширены: поддерживаются expression-arm (`=> expr`) и разделители `,` между arms (включая trailing comma).
- [x] В self-hosted parser `fn`-сигнатуры переключены с balance-only на grammar-level разбор параметров `name: Type` (с `,` и trailing comma), с диагностикой позиции.
- [x] В expression/assignment statement-parser добавлена поддержка compound-assign операторов (`+=`, `-=`, `*=`, `/=`, `%=` и bit/shift assign).
- [x] Host Python parser/translator синхронизирован по assignment operators: поддержаны `+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=` (через lowering в бинарную операцию и присваивание).
- [x] Host Python translator для логических `&&/||` теперь использует short-circuit lowering (`cbr + phi`) вместо eager `and/or`.
- [x] В self-hosted parser добавлен grammar-level разбор tuple struct полей `struct S(T1, T2, ...)` и enum tuple payload `Variant(T1, T2, ...)`, включая trailing comma.
- [x] В self-hosted parser добавлена поддержка unit-struct деклараций (`struct Marker`, включая generic-форму `struct Marker[T]` без тела).
- [x] Expression boundary parser улучшен для infix-конструкций (`a + match ...`) через soft-boundary для `if/match/unsafe`.
- [x] Import grammar ужесточён: wildcard `*` допускается только как терминальный сегмент пути (ошибка на `*::...`).
- [x] Диагностика parser-ошибок расширена: сообщения теперь включают тип текущего токена (даже когда у токена пустой `value`, например `EOF`).
- [x] В `ParseOutcome::Success` добавлены структурированные top-level метаданные директив (`kind/name/public/line/column`) как первый шаг к полноценному AST frontend-а.
- [x] В `ParseOutcome::Success` добавлен `import_bindings_outline` (нормализованные import-binding пути, включая `refrain::` и grouped imports) для следующего шага import-graph/resolver.
- [x] Добавлен безопасный `directives_meta_outline` (string) как fallback для диагностики structured-meta.
- [x] В self-hosted `build` unresolved imports теперь считаются ошибкой сборки (не только логируются).
- [x] В import-graph локальное разрешение импортов расширено до цепочки префиксов (`a::b::c::Symbol` -> проверка `a::b::c`, `a::b`, `a`), чтобы корректнее отличать local module от refrain root.
- [x] Import-graph теперь рекурсивно обходит локальные модули и валит build на транзитивных unresolved imports (не только на imports entry-файла).
- [x] В `build` добавлен детальный вывод unresolved import bindings (`binding -> unresolved:<root>`), чтобы диагностика не ограничивалась только счётчиком.
- [x] Для `refrain::...` в import-graph добавлена валидация dependency root; неизвестные корни теперь корректно маркируются как unresolved.
- [x] `cimp` добавлен как top-level soft-keyword в self-hosted parser (без резервирования токена), а его bindings участвуют в import-graph.
- [x] Host bridge parser поддерживает `cimp` как public import (re-export) для совместимости пайплайна; добавлен smoke-case `examples/cimp_reexport`.
- [x] В parser добавлены отдельные outlines для `pub import` и `cimp`, чтобы import-graph мог различать ре-экспорты.
- [x] Import-graph теперь проверяет existence imported symbol для локальных модулей по export-набору (pub directives + `pub import` + `cimp`), а не только факт существования пути.
- [x] Добавлен negative-case `examples/negative/unresolved_local_symbol` (модуль есть, символ не экспортируется).
- [x] Из manifest в build/import-graph передается root->path карта зависимостей (`path@...`) для проверки `refrain`-импортов не только по root.
- [x] Import-graph теперь выполняет symbol-aware валидацию для `refrain::...` (если root-path известен), включая module-path lookup внутри dependency.
- [x] Manifest-parser в self-hosted build теперь рекурсивно обходит transitive `path@`-зависимости и агрегирует root/path map по всему дереву зависимостей.
- [x] `refrain::<dep>::Symbol` поддержан для root-level экспортов из `src/lib.enq` dependency (раньше резолв ожидал только модульный путь под `src/<module>`).
- [x] `refrain::<module>::<symbol>` внутри текущего проекта (абсолютный path от project `src`) теперь покрыт import-graph и smoke-кейсом `examples/refrain_absolute_import`.
- [x] Host Python frontend синхронизирован: `refrain::` теперь резолвится через transitive dependency roots (не только direct deps).
- [x] Добавлен negative-case `examples/negative/unresolved_refrain_symbol` (refrain root и модуль есть, символ не экспортируется).
- [x] Добавлены negative-cases для project-absolute `refrain::...`: `examples/negative/unresolved_refrain_absolute_import` и `examples/negative/unresolved_refrain_absolute_symbol`.
- [x] Добавлен negative-case `examples/negative/unresolved_transitive_refrain_symbol` (transitive refrain root найден, но символ в dependency не экспортируется).
- [x] Export-набор модуля для `pub import`/`cimp` теперь собирается только из успешно резолвящихся binding-ов (с cycle-guard по visited modules), чтобы не публиковать "ложные" символы.
- [x] Добавлен negative-case `examples/negative/unresolved_public_reexport` (невалидный `pub import` не делает символ публично доступным через модуль).
- [x] Добавлен negative-case `examples/negative/unresolved_public_wildcard_reexport` (невалидный `pub import util::*` не должен давать wildcard-экспорт символов наружу).
- [x] Поддержан shorthand `self` в параметрах методов (`trait`/`impl`) в self-hosted parser и в host Python parser; добавлен smoke-case `examples/method_self`.
- [x] `directives_meta: Vec[ParsedDirective]` снова заполняется в parser через `push_front` без регрессий на текущем smoke/negative наборе.
- [x] Порядок/обход typed-vec стабилизирован: `directives_meta` финализируется через `reverse`, `build` печатает structured-meta из `Vec[ParsedDirective]` (через typed traversal), без crash на текущем smoke/negative наборе.
- [ ] Полный grammar parser (AST directives/expressions/statements) еще не завершен.

### DoD
- Self-hosted frontend выдаёт корректное типизированное AST/eHIR input для smoke и негативных тестов.

## Stage 2: Self-Hosted Lowering to eHIR
- [ ] Полный lowering AST -> eHIR directives/instructions/terminators.
- [ ] Корректная materialization generics и мономорфизация там, где требуется.
- [ ] Lowering `match` как expression, pointer/smart-pointer операций, enum/struct access.
- [ ] Удалить временные textual-hacks в пользу typed eHIR-конструкций.

### DoD
- Для целевого набора примеров eHIR после lowering стабилен и валиден для backend.

## Stage 3: Self-Hosted eHIR Middle-End
- [ ] Портировать/реализовать pass-цепочку: resolver, normalizer, deallocator, cfree, downgrader, postprocessor.
- [ ] Поддержать рекурсивные/циклические типы, enum payload как composite, pointer wrapper layout.
- [ ] Устранить расхождения с Python в lowered форме (где это важно для codegen).

### DoD
- Все eHIR pass запускаются в self-hosted режиме без использования Python.

## Stage 4: Self-Hosted LLVM Backend Core
- [ ] Завершить `eHIR -> LLVM IR` lowering по всем используемым инструкциям.
- [ ] Удалить заглушки в optimizer/assembler/linker/archiver.
- [ ] Реализовать реальную backend-цепочку:
  - `IR -> object` (clang/llc),
  - `object -> static_lib` (ar),
  - `object + runtime -> executable` (clang/ld),
  - `dynamic_lib` (shared linkage).
- [ ] Нормализовать runtime (общий для любых frontend-ов, без привязки к Encore-специфике).

### DoD
- `enc_future build` без host-bridge генерирует `.ir`, `.o`, `.a`, бинарники по target.

## Stage 5: Build System, Refrains, Cache
- [ ] Dependency resolution для refrains (git/path), update/add workflows.
- [ ] Кэш compiled refrains по version/inputs/target/profile/backend.
- [ ] Инвалидация кэша и deterministic artifact paths.
- [ ] Явный режимы `build/run/add/update/init` полностью на self-hosted пайплайне.

Progress:
- [x] `run` режим в self-hosted CLI теперь реально выполняет `build + launch` и передает CLI args в запущенный бинарь.
- [x] `init` реализован: создает `encore.toml`, `src/main.enq`, `README.md`, `.gitignore`, и инициализирует git-репозиторий.
- [x] `add` реализован: добавляет `path@...`/`git@...` dependency в `encore.toml`, проверяет дубликаты и резолвит зависимость (path existence / git clone в `.ehir/cache/git/...`).
- [x] `update` реализован: рекурсивно проходит dependencies (`path@...`) и обновляет/подтягивает `git@...` зависимости в локальном cache.
- [x] Cache loader hardening: поврежденные/неполные JSON cache entries больше не валят build (безопасный fallback на recompute), store пишет атомарно через temporary file.

### DoD
- Повторные сборки корректно используют кэш; update/add/run работают без Python helper-логики.

## Stage 6: Std + Runtime Completeness
- [ ] Закрыть минимальный std для компилятора: `string`, `vec`, `option/result`, `io`, `os`, `cmp`.
- [ ] Укрепить `unsafe` boundary для FFI и системных вызовов.
- [ ] Добавить недостающие runtime-функции для процесса/файлов/строк/путей.

### DoD
- Сам компилятор на Encore не упирается в отсутствующие std/runtime API.

## Stage 7: Test Matrix + Differential Validation
- [ ] Расширить `enc_future/examples` (positive + negative).
- [ ] Golden-тесты на IR, объектники и runtime поведение.
- [ ] Differential tests: Python vs self-hosted (пока Python ещё доступен).
- [ ] Добавить stress/fuzz для lexer/parser/typechecker (минимальный набор).

Progress:
- [x] Есть набор позитивных smoke examples в `enc_future/examples`.
- [x] `examples/run_smoke.sh` теперь явно диагностирует crash по сигналу (как и `run_negative.sh`), вместо немого обрыва на `set -e`.
- [x] Реализованы `update_ir_golden.sh` и `run_ir_golden.sh`.
- [x] Реализован `run_exec_smoke.sh` с проверкой exit code.
- [x] Добавлен отдельный negative regression-набор (`examples/negative`) и раннер `examples/run_negative.sh`.
- [x] Добавлен negative-кейс `invalid_for_statement` для parser-валидации `for ... in ...`.
- [x] Добавлены negative-кейсы `invalid_break_outside_loop` и `invalid_continue_outside_loop`.
- [x] `examples/run_negative.sh` валит ран с явной диагностикой при crash (`status >= 128`, сигнал), чтобы не маскировать segfault как обычный mismatch expected-текста.
- [x] Добавлен smoke-case `examples/transitive_refrain_import` (импорт из transitive refrain dependency).
- [x] Добавлен smoke-case `examples/refrain_absolute_import` (project-absolute `refrain::types::...` import).
- [x] Добавлен smoke-case `examples/method_self` (impl-метод с shorthand `self` + namespaced вызов `Type::method(...)`).
- [x] Добавлен smoke-case `examples/unsafe_fn` (top-level `unsafe fn` parser parity).
- [x] Добавлен smoke-case `examples/compound_assign` (операторы присваивания `+=`, `-=`, `*=`, `/=`, `%=`, `<<=`, `>>=`, `|=`, `&=`, `^=`).
- [x] Добавлен smoke-case `examples/short_circuit` (проверка short-circuit поведения для `&&` и `||`).
- [x] Для `run_exec_smoke.sh` добавлены expected exit-коды новых/обновленных кейсов (`cimp_reexport`, `transitive_refrain_import`, `refrain_absolute_import`).
- [x] IR-golden набор обновлен для текущего smoke-пула (включая `cimp_reexport`, `compound_assign`, `enum_variants`, `import_group`, `refrain_absolute_import`, `transitive_refrain_import`, `try_result`, `unit_struct`, `unsafe_fn`).
- [ ] Object-level golden/diff и differential tests (Python vs self-hosted) пока не закрыты.

### DoD
- Есть стабильный regression suite, ловящий расхождения до bootstrap-перехода.

## Stage 8: Bootstrap and Self-Consistency
- [ ] Bootstrap-1: собрать `enc_future` seed-компилятором.
- [ ] Bootstrap-2: собранным бинарём пересобрать `enc_future`.
- [ ] Bootstrap-3 (опционально): повторить и проверить стабильность артефактов.
- [ ] Удалить host bridge из `run_build` после прохождения bootstrap gate.

### DoD
- Self-hosted компилятор сам себя собирает в CI без Python в runtime path.

## Stage 9: Python Decommission
- [ ] Переключить основной `encore build/run` путь на self-hosted.
- [ ] Оставить Python только как временный fallback (короткий grace period).
- [ ] После периода стабилизации убрать fallback и зафиксировать релиз.
- [ ] Обновить документацию/инструкции/скрипты разработчика.

### DoD
- Производственный путь полностью self-hosted; Python-версия не нужна для обычной сборки.

---

## Порядок выполнения
1. Stage 0
2. Stage 1
3. Stage 2
4. Stage 3
5. Stage 4
6. Stage 5
7. Stage 6
8. Stage 7
9. Stage 8
10. Stage 9

## Ближайший practical фокус
- Закрыть Stage 1 + Stage 2 end-to-end на `examples/while`, `loop`, `structs`, `refrains`.
- После этого немедленно вырезать bridge из `build` на отдельной ветке и довести Stage 4 минимально до `while`.
