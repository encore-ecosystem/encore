# Compiler Logic

This chapter describes the current shape of the EHIR resolver. It focuses on
type resolution inside EHIR functions, because that stage feeds later lowering,
retain/drop insertion and backend validation.

## STIV Model

The resolver uses a three-layer model:

- `ST` - Symbol Table. Built once per module and treated as the global source of
  truth.
- `I` - Instructions. Each instruction is a local constraint node.
- `V` - Variables. Each function has a local `var -> inferred type` table.

`ST` contains functions, extern functions, structs, enums, traits and impls.
Resolver code does not rebuild or mutate that table while resolving functions.

## Event-Driven Resolution

Resolver does not repeatedly scan the whole function until "nothing changed".
Instead, it runs an event-driven work queue:

1. create function-local `V` state from parameters;
2. register each instruction once;
3. record instruction dependencies on variables;
4. enqueue instructions once for initial processing;
5. when a variable becomes more specific, wake only instructions that depend on
   that variable.

This keeps the cost close to the number of real type refinements instead of the
number of full-function rescans.

## Instruction Dependencies

Each instruction participates as a producer or constraint node.

Examples:

- `capprim` seeds a concrete primitive type immediately;
- `add`, `sub`, `mul` and similar operations constrain both operands and the
  output to a compatible numeric type;
- `load` and `store` propagate pointer element types in both directions;
- `capstruct` and `capenum` use declarations from `ST` and argument types from
  `V` to specialize generics;
- `call` and `callvoid` resolve a callable signature from `ST`, then constrain
  arguments and result variables;
- `match` reads the enum type of the condition and assigns payload types to arm
  bindings.

## Variable Refinement

The core operation is monotonic refinement of a variable type.

When resolver learns a new type fact for a variable, it:

1. resolves aliases and built-in names;
2. compares the new fact with the current variable type;
3. stores the more specific type when the fact refines the current state;
4. raises a compile error on incompatible types;
5. wakes dependent instructions only if the variable was refined.

This means variable knowledge only becomes more precise over time. Resolver does
not rely on toggling between alternative states.

## Hidden Reference Representation

Encore surface types and EHIR runtime representation are not identical.
Aggregate values behave as reference types in the language, while EHIR lowers
them through hidden `Box`-based graph nodes. Resolver accounts for that during
compatibility checks and call argument binding.

This is why type resolution cannot be reduced to plain string equality between
surface names. Field access, calls and payload extraction may propagate either a
surface aggregate type or its hidden boxed form depending on the instruction.

## Why This Matters

Later compiler stages assume that EHIR is fully typed:

- postprocessing requires resolved call signatures and field types;
- retain/drop passes need to distinguish value types from reference types;
- backend validation expects concrete instruction operand types.

The event-driven STIV resolver exists to make those guarantees without
repeatedly re-running whole-function type inference.
