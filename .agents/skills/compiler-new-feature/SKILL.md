---
name: compiler-new-feature
description: How to implement new feature in the compiler
disable-model-invocation: false
---

To implement new feature you need follow next steps:

1. Create a new git branch feature/<feature_name> based on trunk
2. Consider existing implementations
3. If suitable, you can design own solution
4. Rerank solutions from previous steps, describe them with advantages and disadvantages
5. If appropriate, describe updates in user experience. For example - how it be represented in language syntax
6. Ask user to choose best one
7. Write end to end tests with full coverage off the new feature. Test real functional, not only successeful parsing and etc
8. Implement selected feature

Then we move to this cycle:
- Run all tests
- If all tests are passed - exit from cycle
- If no - prepare fixing plan
- Implement all fixes according to the plan from previous step

9. Compile two or tree stages of encore compiler with `extreme` profile. This last two versions should be the same
10. If not - return to the cycle
11. Else - you should write mini report about new feature and create PR to trunk branch
