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
- [x] `build` выводит позицию parser-ошибки (`line:column`) в self-hosted режиме.
- [x] Сигнатуры `trait fn`/`extern fn` разведены по границам парсинга (trait-метод завершается на `}` в trait-body, extern остаётся top-level-only).
- [x] `impl` теперь требует явное тело `{ ... }` (раньше мог молча пройти без блока).
- [x] Убраны прямые `enum ==` сравнения в parser-runtime-пути (заменены на `match`-helper), чтобы backend не падал на `icmp` для enum.
- [x] Host Python parser в bridge-пути поддерживает trailing-comma в import group.
- [ ] Host Python parser в bridge-пути ограничен по enum payload (держим smoke examples в совместимом синтаксисе).
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
- [x] Реализованы `update_ir_golden.sh` и `run_ir_golden.sh`.
- [x] Реализован `run_exec_smoke.sh` с проверкой exit code.
- [ ] Негативные examples как отдельный regression-набор пока не оформлены.
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
