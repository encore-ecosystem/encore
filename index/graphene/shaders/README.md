# Graphene shaders

GLSL files in this directory are authoritative shader sources. Generated functions in `src/shaders/triangle.enq` return SPIR-V word vectors consumed by the public `ShaderModule` API, so applications do not require a shader compiler at runtime.

Regenerate and validate a module with `glslc -O` and `spirv-val --target-env vulkan1.2`. Generated arrays preserve the 32-bit words from the resulting SPIR-V module. This temporary workflow will be replaced by the Graphene shader cooker.

Regenerate the lit cube modules with `tools/generate_cube_shaders.sh`. The script validates both modules before replacing the generated Encore source.
