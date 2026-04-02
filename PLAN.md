# Encore Language Ergonomics Plan (for Self-Hosted Compiler Development)

## Цель
Добавить в текущий компилятор (Python-реализацию Encore) именно те конструкции языка, без которых писать self-hosted компилятор неудобно и дорого по времени.

## Что критично не хватает сейчас
- Полноценной объектной эргономики: `impl` + `self` есть частично, но не хватает удобного метода-вызова и стабильной методной модели.
- Слабой работы с ссылочной семантикой: без удобных ссылок/мутабельности код лексера/парсера/IR-builder перегружен копиями.
- Неполного trait-слоя для архитектуры компилятора (интерфейсы фаз, visitor-подход, diagnostics sink).
- Ограниченной выразительности типов для AST/typed-AST/eHIR моделей (alias/newtype/associated concepts).

---

## Stage 1. Struct / Impl / Self как first-class (P0)
- [x] Зафиксировать `impl` для inherent methods как основной стиль кода (вместо free functions + state-struct).
- [x] Поддержать instance-call sugar: `obj.method(args)` с эквивалентом `Type::method(obj, args)`.
- [ ] Стабилизировать `self`-параметр:
  - `self` (by value),
  - `mut self` (parser-sugar уже поддержан, semantics borrow/mutability pending),
  - reference-формы после внедрения ссылок.
- [ ] Добавить связные diagnostics для method resolution:
  - method not found,
  - wrong receiver type,
  - visibility mismatch.

DoD:
- Lexer/Parser/Builder в `enc_future` пишутся как методы структур без workaround-стиля.

## Stage 2. Ссылки и мутабельность (P0)
- [ ] Добавить удобные ссылки для пользовательского кода (`&T`, `&mut T` модель или эквивалентный безопасный слой).
- [ ] Поддержать мутабельный доступ к полям и коллекциям без постоянного value-copy.
- [ ] Добавить минимальные правила aliasing/мутабельности (пусть проще Rust, но формальные и предсказуемые).
- [ ] Дать понятные ошибки на нарушения ссылочных правил.

DoD:
- Парсер/резолвер можно писать с in-place обновлением состояния без тяжелых копий структур.

## Stage 3. Trait-система для архитектуры компилятора (P0)
- [ ] Trait methods + `impl Trait for Type` в стабильной форме.
- [ ] Поддержка generic trait bounds, минимально достаточная для:
  - abstraction over diagnostics reporter,
  - pass interfaces,
  - visitor-like traversal.
- [ ] Четкая метод-резолюция при наличии inherent + trait methods.

DoD:
- Основные фазы компилятора можно разносить по trait-интерфейсам, а не жестко сшивать.

## Stage 4. Типовая эргономика для AST/IR (P1)
- [ ] `type` aliases для длинных/шаблонных сигнатур.
- [ ] `newtype`-паттерн (или эквивалент) для domain-safe идентификаторов:
  - `NodeId`,
  - `SpanId`,
  - `TypeId`.
- [ ] Нормальная generic inference в часто встречающихся конструкциях коллекций и enum.
- [ ] Устойчивый `Result[T, E]` + `?` на всех нужных выражениях.

DoD:
- Модели AST/typed-AST/eHIR описываются компактно и читаемо.

## Stage 5. Match / Pattern Matching для компиляторных задач (P1)
- [ ] Полноценный `match` как expression на уровне frontend/typecheck.
- [ ] Деструктуризация enum/struct в паттернах.
- [ ] Exhaustiveness checking с понятными diagnostics (включая wildcard поведение).
- [ ] Guard-условия для паттернов (`if guard`) как опциональный шаг.

DoD:
- Код семантики и lowering не упирается в chain-if и ручную распаковку enum.

## Stage 6. Модульность и импорты для большого кода (P1)
- [ ] Импорт-эргономика уже выбранного стиля (`import ...`) доводится до production-уровня:
  - alias (`as`) для конфликтующих символов,
  - стабильный re-export (`cimp`/pub import),
  - понятные правила видимости.
- [ ] Улучшить диагностику конфликтов имен и ambiguity.

DoD:
- Кодовая база компилятора делится на модули без шумных workaround-импортов.

## Stage 7. Compile-time удобства (P2)
- [ ] `const`/compile-time literals для таблиц токенов, приоритетов операторов, keyword maps.
- [ ] Минимальная метапрограммная поддержка (если без макросов, то хотя бы генераторные helper-утилиты в std).
- [ ] Улучшение строковой эргономики для лексера/диагностик (срезы, форматирование, интерполяция по необходимости).

DoD:
- Меньше ручного boilerplate в лексере/парсере/diagnostics.

---

## Приоритет внедрения
1. Stage 1
2. Stage 2
3. Stage 3
4. Stage 4
5. Stage 5
6. Stage 6
7. Stage 7

## Minimum Viable Ergonomics (что нужно закрыть первым)
- [x] `impl` + `self` + method-call sugar.
- [ ] Ссылки/мутабельность для stateful компонентов компилятора.
- [ ] Trait-интерфейсы для фаз и диагностик.
- [ ] `type alias` + стабильный `Result`/`?`.
- [ ] Pattern matching с exhaustiveness.

После закрытия этого набора писать self-hosted компилятор будет заметно проще и ближе к нормальному production-style коду.
