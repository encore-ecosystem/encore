---
name: compiler-new-feature
description: How to implement new feature in the compiler
disable-model-invocation: false
---

To implement a new compiler feature, follow these steps:

1. Create a new git branch feature/<feature_name> based on trunk
2. Consider existing implementations
3. If suitable, you can design own solution
4. Rank the solutions from the previous steps and describe their advantages and disadvantages
5. If appropriate, describe updates in user experience. For example - how it be represented in language syntax
6. Ask user to choose best one
7. Write end-to-end tests with full coverage of the new feature. Test real functionality, not only successful parsing
8. Implement selected feature

Then move to this cycle:
- Run all tests
- If all tests pass, exit the cycle
- Otherwise, inspect the complete failures and prepare a fixing plan
- Implement all fixes from that plan before rerunning tests

9. Compile two or three stages of the Encore compiler with the `extreme` profile. The last two versions must be identical
10. If they differ, return to the test-and-fix cycle
11. Before pushing or creating/updating a PR, run the CI-equivalent suite locally in Docker:
    - Reproduce every Linux CI job that can run on the host, including the full test suite, analyzer/CLI contracts, integration tests, and bootstrap convergence
    - Cross-compile and link-check macOS and Windows targets in Docker when the required SDK/toolchain is available
    - Run portable tests for those targets locally where emulation or Wine provides a faithful environment
    - Native OS APIs that Docker cannot faithfully reproduce (for example SecureTransport or Schannel) remain mandatory checks on their native CI runners
    - Treat a local Docker failure exactly like a test failure: inspect all output, prepare a complete fixing plan, implement it, and rerun locally
    - Do not use CI as an exploratory debugger. Push only after the complete applicable Docker suite passes
12. Write a mini-report about the new feature, push the verified branch, create a PR to `trunk`, and monitor the native CI matrix
13. If native CI fails, inspect all available failed-job logs before changing code, reproduce the failure locally when possible, update the fixing plan, rerun the complete applicable Docker suite, and only then push the fix
