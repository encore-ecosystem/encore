# Graphene

Graphene is a real-time engine and editor written in Encore.

The first backend is Vulkan. Public rendering APIs are defined by Graphene RHI and do not expose Vulkan handles, allowing additional native backends later.

The Vulkan bridge is one C translation unit with private implementation fragments: `platform.inc` owns loading, SDL and instance discovery; `device.inc` owns logical devices and pipeline resources; `presentation.inc` owns swapchains and frame recording; `resources.inc` owns command submissions, buffers, textures and transfers. Keeping one translation unit avoids exporting internal Vulkan declarations while preventing the backend from becoming one monolithic implementation file.

## Capability tiers

- Tier 0: Vulkan 1.2-compatible raster and compute foundation.
- Tier 1: Vulkan 1.3 core rendering and synchronization model.
- Tier 2: mesh shader support.
- Tier 3: acceleration structures, ray queries or ray-tracing pipelines.

Ray tracing and mesh shaders are optional capabilities. Graphene must remain functional on Tier 0 and Tier 1 adapters.

`GraphicsDevice` owns one graphics queue, preferring a queue family that also supports compute. Devices must be destroyed before their parent `GraphicsInstance`.

`CommandEncoder` owns a primary, one-time command buffer. Submitting it transfers the command buffer to `GpuSubmission`, which exposes fence polling and bounded waits. The synchronous path remains available for initialization.

`GpuBuffer` supports device-local or host-visible allocation. The first implementation uses one Vulkan allocation per buffer; the public API is independent from the allocator strategy.

Static geometry should live in device-local memory. Create a host-visible `buffer_transfer_source` staging buffer, copy it into a device-local vertex or index buffer carrying `buffer_transfer_destination`, wait for the upload submission, then release staging memory.

`GraphicsDevice::create_mesh` packages that upload path for interleaved `f32` vertices and `u32` indices. `GpuMesh` owns the resulting device-local buffers, and `RenderPassEncoder::draw_mesh` binds and draws them. Destroy a mesh only after submissions that reference it have completed.

The scene layer remains independent from the RHI. `Transform` stores position, Euler rotation and scale, while `Scene` assigns stable entity IDs and resolves parent-child world matrices. Parenting rejects missing entities, self-parenting and cycles. Visibility is inherited through the parent chain. Entities contain serializable engine data rather than backend handles.

`Renderable` attaches backend-neutral `MeshId` and `MaterialId` values to an entity. `Scene::visible_render_items` resolves hierarchy and emits a render queue containing only valid, world-visible objects. Asset IDs are stable scene references; renderer asset registries map them to backend resources.

`MeshAssets` uploads CPU `MeshData`, owns the resulting `GpuMesh` resources and resolves stable `MeshId` values while recording draws. It intentionally does not expose owned mesh handles, preventing accidental double destruction. `MaterialAssets` stores `StandardMaterial` values keyed by `MaterialId`; base color, metallic and roughness are uploaded with each object's frame-ring uniform and affect the lit shader.

The scene layer also provides CPU-side `MeshData`, built-in primitive generation and `DirectionalLight`. `cube_mesh` emits 24 position/normal/color vertices so each face keeps a flat normal, plus 36 consistently wound indices. The lit cube shader consumes model and camera matrices with directional light parameters from a frame-ring uniform.

`ObjectUniforms` is the renderer-side bridge for a visible object. It owns one 192-byte uniform buffer and bind group per frame in flight, updates only the acquired frame slot, and keeps this transient GPU state outside `Scene`. Applications must destroy it before its bind-group layout and device.

`GpuTexture` supports device-local 2D images with explicit format, usage and mip count. Texture upload and layout transitions are recorded separately by command encoders.

Textures own a Vulkan image view. Staging uploads use an explicit transfer-destination transition, buffer-to-image copy and shader-read transition; the same Graphene commands will map to synchronization2 when that backend path is enabled.

## Presentation

Window support is opt-in through `GraphicsInstance::with_window_support`. Graphene loads SDL3 dynamically for native window and Vulkan surface creation; headless tools and CI do not require SDL3.

Create presentation objects in this order: `GraphicsInstance`, `GrapheneWindow`, present-capable `GraphicsDevice`, `Swapchain`, shader modules, and `RenderPipeline`. GPU buffers can be created after the device. Destroy the swapchain before pipelines currently used by its framebuffers, then destroy pipelines, shaders, buffers, device, window and instance. The swapchain uses FIFO presentation and automatically rebuilds itself when Wayland, X11 or the compositor invalidates its extent.

The swapchain keeps two frames in flight, each with persistent command buffers, semaphores and a fence. Rendering waits only when reusing a frame slot; queue-wide idle waits are reserved for swapchain rebuild and destruction.

Dynamic resources must also be ring-buffered. `RenderFrame::slot` identifies the frame whose fence has already been waited by `acquire_frame`; update only the uniform or staging range owned by that slot. `Swapchain::frames_in_flight` reports the required ring size.

`ShaderModule` accepts SPIR-V words directly from Encore. `RenderPipeline` describes its interleaved vertex layout independently from the swapchain extent, and `Swapchain::draw_indexed` binds vertex and `u32` index buffers. Dynamic viewport and scissor state keep a pipeline valid across window resize.

`BindGroupLayout` describes typed bindings visible to selected shader stages. The current descriptor types are uniform buffers and combined texture samplers. `BindGroup` owns its descriptor pool and set, references bounded resources, and can be bound by `Swapchain::draw_indexed_bound`. The API names intentionally match the future backend-neutral resource model rather than exposing Vulkan descriptor terminology.

`GpuSampler` currently provides linear filtering, linear mip selection and edge clamping. Material bind groups combine a uniform range with a shader-readable `GpuTexture` and sampler; sampler configuration will become a descriptor before additional filtering modes are exposed.

Depth-tested render pipelines use a `D32` attachment with `LESS` comparison and depth writes. Depth is opt-in through `create_depth_render_pipeline`; regular pipelines remain suitable for UI and coplanar overlays. Swapchains allocate one depth image per presentation image, so frames in flight never race on shared depth storage. Depth images are recreated with the swapchain extent.

`RenderPipelineOptions` controls depth testing, front/back-face culling and straight-alpha blending without exposing Vulkan enums. Opaque 3D meshes normally use depth plus back-face culling; transparent UI and materials use alpha blending and usually disable depth writes.

Frame recording is explicit. `Swapchain::acquire_frame` returns a `RenderFrame`; the frame begins a `RenderPassEncoder`, which binds groups and vertex/index buffers and records draws. Ending the pass does not submit it. `RenderFrame::present` finalizes the command buffer, submits it with the frame-slot fence and semaphores, and presents the acquired image. Destroying an unfinished frame safely finalizes it so an acquired swapchain image is not stranded.

The triangle shaders are compiled to SPIR-V offline. Applications do not invoke a shader compiler or depend on `glslc` at runtime. The checked-in GLSL remains the authoritative source; generated Encore functions return SPIR-V word vectors until Graphene gets its shader cooker.

Every directory under `examples/` is a Graphene project. Open the example directory from the editor; its runnable Encore package is stored in `game/`.

## Adapter probe

```sh
cd examples/adapter_info/game
encore run
```

## Triangle probe

```sh
cd examples/clear_window/game
encore run
```

## Depth probe

```sh
cd examples/depth_test/game
encore run
```

## Camera and cube probe

```sh
cd examples/cube/game
encore run
```

Set `GRAPHENE_VK_TRACE=1` to print surface extents and Vulkan acquire/present results while diagnosing platform presentation.

Window input uses physical keyboard scancodes and a per-poll mouse snapshot. In the cube probe, use `A/D` to orbit, `W/S` to zoom, drag with the right mouse button to orbit freely, and press `Escape` to exit.
