/* Swapchain lifecycle, explicit frame recording and presentation. */
static bool graphene_vk_swapchain_create_render_support(GrapheneVkSwapchain *swapchain) {
    GrapheneVkDevice *device = swapchain->owner;
    PFN_vkCreateFramebuffer create_framebuffer = (PFN_vkCreateFramebuffer)device->get_device_proc(device->device, "vkCreateFramebuffer");
    PFN_vkCreateImageView create_image_view = (PFN_vkCreateImageView)device->get_device_proc(device->device, "vkCreateImageView");
    swapchain->destroy_image_view = (PFN_vkDestroyImageView)device->get_device_proc(device->device, "vkDestroyImageView");
    swapchain->destroy_framebuffer = (PFN_vkDestroyFramebuffer)device->get_device_proc(device->device, "vkDestroyFramebuffer");
    swapchain->cmd_begin_render_pass = (PFN_vkCmdBeginRenderPass)device->get_device_proc(device->device, "vkCmdBeginRenderPass");
    swapchain->cmd_end_render_pass = (PFN_vkCmdEndRenderPass)device->get_device_proc(device->device, "vkCmdEndRenderPass");
    swapchain->cmd_bind_pipeline = (PFN_vkCmdBindPipeline)device->get_device_proc(device->device, "vkCmdBindPipeline");
    swapchain->cmd_draw = (PFN_vkCmdDraw)device->get_device_proc(device->device, "vkCmdDraw");
    swapchain->cmd_set_viewport = (PFN_vkCmdSetViewport)device->get_device_proc(device->device, "vkCmdSetViewport");
    swapchain->cmd_set_scissor = (PFN_vkCmdSetScissor)device->get_device_proc(device->device, "vkCmdSetScissor");
    swapchain->cmd_bind_vertex_buffers = (PFN_vkCmdBindVertexBuffers)device->get_device_proc(device->device, "vkCmdBindVertexBuffers");
    swapchain->cmd_bind_index_buffer = (PFN_vkCmdBindIndexBuffer)device->get_device_proc(device->device, "vkCmdBindIndexBuffer");
    swapchain->cmd_draw_indexed = (PFN_vkCmdDrawIndexed)device->get_device_proc(device->device, "vkCmdDrawIndexed");
    swapchain->cmd_bind_descriptor_sets = (PFN_vkCmdBindDescriptorSets)device->get_device_proc(device->device, "vkCmdBindDescriptorSets");
    swapchain->create_framebuffer = create_framebuffer;
    if (create_framebuffer == NULL || create_image_view == NULL || swapchain->destroy_image_view == NULL ||
        swapchain->destroy_framebuffer == NULL || swapchain->cmd_begin_render_pass == NULL ||
        swapchain->cmd_end_render_pass == NULL || swapchain->cmd_bind_pipeline == NULL || swapchain->cmd_draw == NULL ||
        swapchain->cmd_set_viewport == NULL || swapchain->cmd_set_scissor == NULL ||
        swapchain->cmd_bind_vertex_buffers == NULL || swapchain->cmd_bind_index_buffer == NULL ||
        swapchain->cmd_draw_indexed == NULL || swapchain->cmd_bind_descriptor_sets == NULL) {
        strncpy(swapchain->error, "Required Vulkan graphics pipeline functions were not found", sizeof(swapchain->error) - 1); return false;
    }
    swapchain->views = (void **)calloc(swapchain->image_count, sizeof(void *));
    swapchain->depth_images = (void **)calloc(swapchain->image_count, sizeof(void *));
    swapchain->depth_views = (void **)calloc(swapchain->image_count, sizeof(void *));
    swapchain->depth_memories = (void **)calloc(swapchain->image_count, sizeof(void *));
    swapchain->framebuffers = (void **)calloc(swapchain->image_count, sizeof(void *));
    if (swapchain->views == NULL || swapchain->depth_images == NULL || swapchain->depth_views == NULL ||
        swapchain->depth_memories == NULL || swapchain->framebuffers == NULL) {
        strncpy(swapchain->error, "Unable to allocate swapchain render resources", sizeof(swapchain->error) - 1); return false;
    }
    for (uint32_t i = 0; i < swapchain->image_count; ++i) {
        VkImageViewCreateInfo view = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, swapchain->images[i], 1,
            swapchain->format, {0, 0, 0, 0}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        if (create_image_view(device->device, &view, NULL, &swapchain->views[i]) != VK_SUCCESS) {
            strncpy(swapchain->error, "Unable to create a swapchain image view", sizeof(swapchain->error) - 1); return false;
        }
        VkImageCreateInfo depth_image = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, NULL, 0, 1, 126,
            {swapchain->width, swapchain->height, 1}, 1, 1, VK_SAMPLE_COUNT_1_BIT, 0,
            32, 0, 0, NULL, VK_IMAGE_LAYOUT_UNDEFINED};
        if (device->create_image(device->device, &depth_image, NULL, &swapchain->depth_images[i]) != VK_SUCCESS) {
            strncpy(swapchain->error, "Unable to create swapchain depth image", sizeof(swapchain->error) - 1); return false;
        }
        VkMemoryRequirements depth_requirements;
        device->get_image_requirements(device->device, swapchain->depth_images[i], &depth_requirements);
        uint32_t depth_memory_type = graphene_memory_type(device, depth_requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if (depth_memory_type == UINT32_MAX) depth_memory_type = graphene_memory_type(device, depth_requirements.memoryTypeBits, 0);
        if (depth_memory_type == UINT32_MAX) {
            strncpy(swapchain->error, "No compatible depth image memory", sizeof(swapchain->error) - 1); return false;
        }
        VkMemoryAllocateInfo depth_allocation = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL,
            depth_requirements.size, depth_memory_type};
        if (device->allocate_memory(device->device, &depth_allocation, NULL, &swapchain->depth_memories[i]) != VK_SUCCESS ||
            device->bind_image_memory(device->device, swapchain->depth_images[i], swapchain->depth_memories[i], 0) != VK_SUCCESS) {
            strncpy(swapchain->error, "Unable to allocate swapchain depth image", sizeof(swapchain->error) - 1); return false;
        }
        VkImageViewCreateInfo depth_view = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, swapchain->depth_images[i], 1,
            126, {0, 0, 0, 0}, {VK_IMAGE_ASPECT_DEPTH_BIT, 0, 1, 0, 1}};
        if (create_image_view(device->device, &depth_view, NULL, &swapchain->depth_views[i]) != VK_SUCCESS) {
            strncpy(swapchain->error, "Unable to create swapchain depth view", sizeof(swapchain->error) - 1); return false;
        }
    }
    return true;
}

static size_t graphene_vk_swapchain_create_internal(size_t device_handle, size_t window_handle, uint64_t old_swapchain) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkWindow *window = (GrapheneVkWindow *)window_handle;
    GrapheneVkSwapchain *result = (GrapheneVkSwapchain *)calloc(1, sizeof(GrapheneVkSwapchain));
    if (result == NULL) return 0;
    result->owner = device;
    result->window = window;
    if (device == NULL || !device->available || !device->present || window == NULL ||
        window->surface == 0 || window->owner != device->context) {
        strncpy(result->error, "Invalid presentation device or window", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR get_capabilities =
        (PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR)device->context->get_proc(device->context->instance,
            "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
    PFN_vkGetPhysicalDeviceSurfaceFormatsKHR get_formats =
        (PFN_vkGetPhysicalDeviceSurfaceFormatsKHR)device->context->get_proc(device->context->instance,
            "vkGetPhysicalDeviceSurfaceFormatsKHR");
    PFN_vkCreateSwapchainKHR create_swapchain = (PFN_vkCreateSwapchainKHR)
        device->get_device_proc(device->device, "vkCreateSwapchainKHR");
    PFN_vkGetSwapchainImagesKHR get_images = (PFN_vkGetSwapchainImagesKHR)
        device->get_device_proc(device->device, "vkGetSwapchainImagesKHR");
    PFN_vkCreateSemaphore create_semaphore = (PFN_vkCreateSemaphore)
        device->get_device_proc(device->device, "vkCreateSemaphore");
    result->destroy_swapchain = (PFN_vkDestroySwapchainKHR)device->get_device_proc(device->device, "vkDestroySwapchainKHR");
    result->acquire_next_image = (PFN_vkAcquireNextImageKHR)device->get_device_proc(device->device, "vkAcquireNextImageKHR");
    result->queue_present = (PFN_vkQueuePresentKHR)device->get_device_proc(device->device, "vkQueuePresentKHR");
    result->destroy_semaphore = (PFN_vkDestroySemaphore)device->get_device_proc(device->device, "vkDestroySemaphore");
    result->reset_fences = (PFN_vkResetFences)device->get_device_proc(device->device, "vkResetFences");
    result->cmd_clear_color_image = (PFN_vkCmdClearColorImage)device->get_device_proc(device->device, "vkCmdClearColorImage");
    if (get_capabilities == NULL || get_formats == NULL || create_swapchain == NULL || get_images == NULL ||
        create_semaphore == NULL || result->destroy_swapchain == NULL || result->acquire_next_image == NULL ||
        result->queue_present == NULL || result->destroy_semaphore == NULL || result->reset_fences == NULL ||
        result->cmd_clear_color_image == NULL) {
        strncpy(result->error, "Required Vulkan swapchain functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkSurfaceCapabilitiesKHR capabilities;
    uint32_t format_count = 0;
    if (get_capabilities(device->physical_device, window->surface, &capabilities) != VK_SUCCESS ||
        get_formats(device->physical_device, window->surface, &format_count, NULL) != VK_SUCCESS || format_count == 0) {
        strncpy(result->error, "Unable to query Vulkan surface", sizeof(result->error) - 1); return (size_t)result;
    }
    VkSurfaceFormatKHR *formats = (VkSurfaceFormatKHR *)calloc(format_count, sizeof(VkSurfaceFormatKHR));
    if (formats == NULL || get_formats(device->physical_device, window->surface, &format_count, formats) != VK_SUCCESS) {
        free(formats); strncpy(result->error, "Unable to query Vulkan surface formats", sizeof(result->error) - 1); return (size_t)result;
    }
    VkSurfaceFormatKHR chosen = formats[0];
    for (uint32_t i = 0; i < format_count; ++i) {
        if (formats[i].format == VK_FORMAT_B8G8R8A8_SRGB || formats[i].format == VK_FORMAT_B8G8R8A8_UNORM) {
            chosen = formats[i]; if (formats[i].format == VK_FORMAT_B8G8R8A8_SRGB) break;
        }
    }
    free(formats);
    VkExtent2D extent = capabilities.currentExtent;
    if (extent.width == UINT32_MAX) {
        extent.width = window->width < capabilities.minImageExtent.width ? capabilities.minImageExtent.width : window->width;
        if (extent.width > capabilities.maxImageExtent.width) extent.width = capabilities.maxImageExtent.width;
        extent.height = window->height < capabilities.minImageExtent.height ? capabilities.minImageExtent.height : window->height;
        if (extent.height > capabilities.maxImageExtent.height) extent.height = capabilities.maxImageExtent.height;
    }
    if (graphene_vk_trace_enabled()) {
        fprintf(stderr, "graphene-vk: window=%ux%u current=%ux%u min=%ux%u max=%ux%u selected=%ux%u images=%u..%u\n",
            window->width, window->height, capabilities.currentExtent.width, capabilities.currentExtent.height,
            capabilities.minImageExtent.width, capabilities.minImageExtent.height,
            capabilities.maxImageExtent.width, capabilities.maxImageExtent.height,
            extent.width, extent.height, capabilities.minImageCount, capabilities.maxImageCount);
    }
    uint32_t image_count = capabilities.minImageCount + 1;
    if (capabilities.maxImageCount != 0 && image_count > capabilities.maxImageCount) image_count = capabilities.maxImageCount;
    VkSwapchainCreateInfoKHR info = {VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, NULL, 0, window->surface,
        image_count, chosen.format, chosen.colorSpace, extent, 1,
        VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
        0, 0, NULL,
        capabilities.currentTransform, VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR, VK_PRESENT_MODE_FIFO_KHR, 1, old_swapchain};
    if (create_swapchain(device->device, &info, NULL, &result->swapchain) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create Vulkan swapchain", sizeof(result->error) - 1); return (size_t)result;
    }
    if (get_images(device->device, result->swapchain, &result->image_count, NULL) != VK_SUCCESS || result->image_count == 0) {
        strncpy(result->error, "Unable to enumerate Vulkan swapchain images", sizeof(result->error) - 1); return (size_t)result;
    }
    result->images = (void **)calloc(result->image_count, sizeof(void *));
    if (result->images == NULL || get_images(device->device, result->swapchain, &result->image_count, result->images) != VK_SUCCESS) {
        strncpy(result->error, "Unable to store Vulkan swapchain images", sizeof(result->error) - 1); return (size_t)result;
    }
    VkSemaphoreCreateInfo semaphore_info = {VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO, NULL, 0};
    VkFenceCreateInfo fence_info = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL, VK_FENCE_CREATE_SIGNALED_BIT};
    VkCommandBufferAllocateInfo allocation = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, device->command_pool,
        VK_COMMAND_BUFFER_LEVEL_PRIMARY, 2};
    if (device->allocate_command_buffers(device->device, &allocation, result->command_buffers) != VK_SUCCESS) {
        strncpy(result->error, "Unable to allocate Vulkan frame command buffers", sizeof(result->error) - 1); return (size_t)result;
    }
    for (uint32_t frame = 0; frame < 2; ++frame) {
        if (create_semaphore(device->device, &semaphore_info, NULL, &result->image_available[frame]) != VK_SUCCESS ||
            create_semaphore(device->device, &semaphore_info, NULL, &result->render_finished[frame]) != VK_SUCCESS ||
            device->create_fence(device->device, &fence_info, NULL, &result->fences[frame]) != VK_SUCCESS) {
            strncpy(result->error, "Unable to create Vulkan frame synchronization", sizeof(result->error) - 1); return (size_t)result;
        }
    }
    result->format = chosen.format; result->width = extent.width; result->height = extent.height;
    result->readback_pitch = extent.width * 4;
    VkBufferCreateInfo readback_info = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0,
        (uint64_t)result->readback_pitch * extent.height, 3, 0, 0, NULL};
    if (device->create_buffer(device->device, &readback_info, NULL, &result->readback_buffer) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create viewport readback buffer", sizeof(result->error) - 1); return (size_t)result;
    }
    VkMemoryRequirements readback_requirements;
    device->get_buffer_requirements(device->device, result->readback_buffer, &readback_requirements);
    uint32_t readback_type = graphene_memory_type(device, readback_requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (readback_type == UINT32_MAX) {
        strncpy(result->error, "No host-visible memory for viewport readback", sizeof(result->error) - 1); return (size_t)result;
    }
    VkMemoryAllocateInfo readback_allocation = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL,
        readback_requirements.size, readback_type};
    if (device->allocate_memory(device->device, &readback_allocation, NULL, &result->readback_memory) != VK_SUCCESS ||
        device->bind_buffer_memory(device->device, result->readback_buffer, result->readback_memory, 0) != VK_SUCCESS ||
        device->map_memory(device->device, result->readback_memory, 0, readback_requirements.size, 0,
            &result->readback_pixels) != VK_SUCCESS) {
        strncpy(result->error, "Unable to map viewport readback buffer", sizeof(result->error) - 1); return (size_t)result;
    }
    if (device->create_buffer(device->device, &readback_info, NULL, &result->ui_staging_buffer) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create second UI staging buffer", sizeof(result->error) - 1); return (size_t)result;
    }
    VkMemoryRequirements ui_staging_requirements;
    device->get_buffer_requirements(device->device, result->ui_staging_buffer, &ui_staging_requirements);
    uint32_t ui_staging_type = graphene_memory_type(device, ui_staging_requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkMemoryAllocateInfo ui_staging_allocation = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL,
        ui_staging_requirements.size, ui_staging_type};
    if (ui_staging_type == UINT32_MAX ||
        device->allocate_memory(device->device, &ui_staging_allocation, NULL, &result->ui_staging_memory) != VK_SUCCESS ||
        device->bind_buffer_memory(device->device, result->ui_staging_buffer, result->ui_staging_memory, 0) != VK_SUCCESS ||
        device->map_memory(device->device, result->ui_staging_memory, 0, ui_staging_requirements.size, 0,
            &result->ui_staging_pixels) != VK_SUCCESS) {
        strncpy(result->error, "Unable to map second UI staging buffer", sizeof(result->error) - 1); return (size_t)result;
    }
    if (!graphene_vk_swapchain_create_render_support(result)) return (size_t)result;
    result->available = true;
    return (size_t)result;
}

size_t graphene_vk_swapchain_create(size_t device_handle, size_t window_handle) {
    return graphene_vk_swapchain_create_internal(device_handle, window_handle, 0);
}

size_t graphene_vk_offscreen_create(size_t device_handle, uint32_t width, uint32_t height) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkSwapchain *result = (GrapheneVkSwapchain *)calloc(1, sizeof(GrapheneVkSwapchain));
    if (result == NULL) return 0;
    result->owner = device;
    result->offscreen = true;
    result->image_count = 2;
    result->format = VK_FORMAT_B8G8R8A8_UNORM;
    result->width = width;
    result->height = height;
    if (device == NULL || !device->available || (device->queue_flags & VK_QUEUE_GRAPHICS_BIT) == 0 ||
        width == 0 || height == 0) {
        strncpy(result->error, "Invalid offscreen target device or dimensions", sizeof(result->error) - 1);
        return (size_t)result;
    }
    result->reset_fences = (PFN_vkResetFences)device->get_device_proc(device->device, "vkResetFences");
    if (result->reset_fences == NULL) {
        strncpy(result->error, "Required offscreen synchronization function was not found", sizeof(result->error) - 1);
        return (size_t)result;
    }
    result->images = (void **)calloc(result->image_count, sizeof(void *));
    result->color_memories = (void **)calloc(result->image_count, sizeof(void *));
    if (result->images == NULL || result->color_memories == NULL) {
        strncpy(result->error, "Unable to allocate offscreen color resources", sizeof(result->error) - 1);
        return (size_t)result;
    }
    for (uint32_t i = 0; i < result->image_count; ++i) {
        VkImageCreateInfo color_image = {VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, NULL, 0, 1, result->format,
            {width, height, 1}, 1, 1, VK_SAMPLE_COUNT_1_BIT, 0,
            VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, 0, 0, NULL,
            VK_IMAGE_LAYOUT_UNDEFINED};
        if (device->create_image(device->device, &color_image, NULL, &result->images[i]) != VK_SUCCESS) {
            strncpy(result->error, "Unable to create offscreen color image", sizeof(result->error) - 1);
            return (size_t)result;
        }
        VkMemoryRequirements requirements;
        device->get_image_requirements(device->device, result->images[i], &requirements);
        uint32_t memory_type = graphene_memory_type(device, requirements.memoryTypeBits,
            VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if (memory_type == UINT32_MAX) memory_type = graphene_memory_type(device, requirements.memoryTypeBits, 0);
        if (memory_type == UINT32_MAX) {
            strncpy(result->error, "No compatible offscreen color memory", sizeof(result->error) - 1);
            return (size_t)result;
        }
        VkMemoryAllocateInfo allocation = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL,
            requirements.size, memory_type};
        if (device->allocate_memory(device->device, &allocation, NULL, &result->color_memories[i]) != VK_SUCCESS ||
            device->bind_image_memory(device->device, result->images[i], result->color_memories[i], 0) != VK_SUCCESS) {
            strncpy(result->error, "Unable to allocate offscreen color image", sizeof(result->error) - 1);
            return (size_t)result;
        }
    }
    VkCommandBufferAllocateInfo command_allocation = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL,
        device->command_pool, VK_COMMAND_BUFFER_LEVEL_PRIMARY, 2};
    if (device->allocate_command_buffers(device->device, &command_allocation, result->command_buffers) != VK_SUCCESS) {
        strncpy(result->error, "Unable to allocate offscreen command buffers", sizeof(result->error) - 1);
        return (size_t)result;
    }
    VkFenceCreateInfo fence_info = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL, VK_FENCE_CREATE_SIGNALED_BIT};
    for (uint32_t frame = 0; frame < 2; ++frame) {
        if (device->create_fence(device->device, &fence_info, NULL, &result->fences[frame]) != VK_SUCCESS) {
            strncpy(result->error, "Unable to create offscreen frame fence", sizeof(result->error) - 1);
            return (size_t)result;
        }
    }
    result->readback_pitch = width * 4;
    VkBufferCreateInfo readback_info = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0,
        (uint64_t)result->readback_pitch * height, 2, 0, 0, NULL};
    if (device->create_buffer(device->device, &readback_info, NULL, &result->readback_buffer) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create offscreen readback buffer", sizeof(result->error) - 1);
        return (size_t)result;
    }
    VkMemoryRequirements readback_requirements;
    device->get_buffer_requirements(device->device, result->readback_buffer, &readback_requirements);
    uint32_t readback_type = graphene_memory_type(device, readback_requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (readback_type == UINT32_MAX) {
        strncpy(result->error, "No host-visible offscreen readback memory", sizeof(result->error) - 1);
        return (size_t)result;
    }
    VkMemoryAllocateInfo readback_allocation = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL,
        readback_requirements.size, readback_type};
    if (device->allocate_memory(device->device, &readback_allocation, NULL, &result->readback_memory) != VK_SUCCESS ||
        device->bind_buffer_memory(device->device, result->readback_buffer, result->readback_memory, 0) != VK_SUCCESS ||
        device->map_memory(device->device, result->readback_memory, 0, readback_requirements.size, 0,
            &result->readback_pixels) != VK_SUCCESS) {
        strncpy(result->error, "Unable to map offscreen readback buffer", sizeof(result->error) - 1);
        return (size_t)result;
    }
    if (!graphene_vk_swapchain_create_render_support(result)) return (size_t)result;
    result->available = true;
    if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: offscreen=%ux%u images=%u\n",
        width, height, result->image_count);
    return (size_t)result;
}

static void graphene_vk_swapchain_release_render_resources(GrapheneVkSwapchain *swapchain) {
    GrapheneVkDevice *device = swapchain->owner;
    if (device == NULL || device->device == NULL) return;
    if (swapchain->framebuffers != NULL && swapchain->destroy_framebuffer != NULL) {
        for (uint32_t i = 0; i < swapchain->image_count; ++i)
            if (swapchain->framebuffers[i] != NULL) swapchain->destroy_framebuffer(device->device, swapchain->framebuffers[i], NULL);
    }
    if (swapchain->views != NULL && swapchain->destroy_image_view != NULL) {
        for (uint32_t i = 0; i < swapchain->image_count; ++i)
            if (swapchain->views[i] != NULL) swapchain->destroy_image_view(device->device, swapchain->views[i], NULL);
    }
    if (swapchain->depth_views != NULL && swapchain->destroy_image_view != NULL) {
        for (uint32_t i = 0; i < swapchain->image_count; ++i)
            if (swapchain->depth_views[i] != NULL) swapchain->destroy_image_view(device->device, swapchain->depth_views[i], NULL);
    }
    if (swapchain->depth_images != NULL) for (uint32_t i = 0; i < swapchain->image_count; ++i)
        if (swapchain->depth_images[i] != NULL) device->destroy_image(device->device, swapchain->depth_images[i], NULL);
    if (swapchain->depth_memories != NULL) for (uint32_t i = 0; i < swapchain->image_count; ++i)
        if (swapchain->depth_memories[i] != NULL) device->free_memory(device->device, swapchain->depth_memories[i], NULL);
    if (swapchain->offscreen && swapchain->images != NULL) for (uint32_t i = 0; i < swapchain->image_count; ++i)
        if (swapchain->images[i] != NULL) device->destroy_image(device->device, swapchain->images[i], NULL);
    if (swapchain->color_memories != NULL) for (uint32_t i = 0; i < swapchain->image_count; ++i)
        if (swapchain->color_memories[i] != NULL) device->free_memory(device->device, swapchain->color_memories[i], NULL);
    free(swapchain->framebuffers);
    free(swapchain->views);
    free(swapchain->depth_views);
    free(swapchain->depth_images);
    free(swapchain->depth_memories);
    free(swapchain->color_memories);
}

static void graphene_vk_swapchain_release_readback(GrapheneVkSwapchain *swapchain) {
    GrapheneVkDevice *device = swapchain == NULL ? NULL : swapchain->owner;
    if (device == NULL || device->device == NULL) return;
    if (swapchain->readback_pixels != NULL && swapchain->readback_memory != NULL)
        device->unmap_memory(device->device, swapchain->readback_memory);
    if (swapchain->ui_staging_pixels != NULL && swapchain->ui_staging_memory != NULL)
        device->unmap_memory(device->device, swapchain->ui_staging_memory);
    if (swapchain->readback_buffer != NULL) device->destroy_buffer(device->device, swapchain->readback_buffer, NULL);
    if (swapchain->ui_staging_buffer != NULL) device->destroy_buffer(device->device, swapchain->ui_staging_buffer, NULL);
    if (swapchain->readback_memory != NULL) device->free_memory(device->device, swapchain->readback_memory, NULL);
    if (swapchain->ui_staging_memory != NULL) device->free_memory(device->device, swapchain->ui_staging_memory, NULL);
    swapchain->readback_pixels = NULL; swapchain->readback_buffer = NULL; swapchain->readback_memory = NULL;
    swapchain->ui_staging_pixels = NULL; swapchain->ui_staging_buffer = NULL; swapchain->ui_staging_memory = NULL;
}

static bool graphene_vk_swapchain_rebuild(GrapheneVkSwapchain *swapchain) {
    GrapheneVkDevice *device = swapchain->owner;
    if (swapchain->window->owns_window) graphene_vk_window_poll((size_t)swapchain->window);
    else graphene_vk_window_refresh(swapchain->window);
    GrapheneVkSwapchain *fresh = (GrapheneVkSwapchain *)graphene_vk_swapchain_create_internal(
        (size_t)device, (size_t)swapchain->window, swapchain->swapchain);
    if (fresh == NULL || !fresh->available) {
        if (fresh != NULL) {
            if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: rebuild failed: %s\n", fresh->error);
            strncpy(swapchain->error, fresh->error, sizeof(swapchain->error) - 1);
            graphene_vk_swapchain_destroy((size_t)fresh);
        }
        return false;
    }
    device->queue_wait_idle(device->queue);
    if (swapchain->command_buffers[0] != NULL)
        device->free_command_buffers(device->device, device->command_pool, 2, swapchain->command_buffers);
    for (uint32_t frame = 0; frame < 2; ++frame) {
        if (swapchain->image_available[frame] != NULL) swapchain->destroy_semaphore(device->device, swapchain->image_available[frame], NULL);
        if (swapchain->render_finished[frame] != NULL) swapchain->destroy_semaphore(device->device, swapchain->render_finished[frame], NULL);
        if (swapchain->fences[frame] != NULL) device->destroy_fence(device->device, swapchain->fences[frame], NULL);
    }
    graphene_vk_swapchain_release_render_resources(swapchain);
    graphene_vk_swapchain_release_readback(swapchain);
    if (swapchain->swapchain != 0) swapchain->destroy_swapchain(device->device, swapchain->swapchain, NULL);
    free(swapchain->images);
    *swapchain = *fresh;
    free(fresh);
    return true;
}

static bool graphene_vk_swapchain_prepare_pipeline(GrapheneVkSwapchain *swapchain, GrapheneVkPipeline *pipeline) {
    if (pipeline == NULL || !pipeline->available || pipeline->owner != swapchain->owner || pipeline->format != swapchain->format) {
        strncpy(swapchain->error, "Render pipeline is incompatible with this swapchain", sizeof(swapchain->error) - 1); return false;
    }
    if (swapchain->active_render_pass == pipeline->render_pass) return true;
    GrapheneVkDevice *device = swapchain->owner;
    device->queue_wait_idle(device->queue);
    for (uint32_t i = 0; i < swapchain->image_count; ++i) {
        if (swapchain->framebuffers[i] != NULL) {
            swapchain->destroy_framebuffer(device->device, swapchain->framebuffers[i], NULL);
            swapchain->framebuffers[i] = NULL;
        }
        void *attachments[2] = {swapchain->views[i], swapchain->depth_views[i]};
        VkFramebufferCreateInfo framebuffer = {VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, NULL, 0,
            pipeline->render_pass, pipeline->depth_test ? 2 : 1, attachments, swapchain->width, swapchain->height, 1};
        if (swapchain->create_framebuffer(device->device, &framebuffer, NULL, &swapchain->framebuffers[i]) != VK_SUCCESS) {
            strncpy(swapchain->error, "Unable to create pipeline framebuffer", sizeof(swapchain->error) - 1); return false;
        }
    }
    swapchain->active_render_pass = pipeline->render_pass;
    return true;
}

size_t graphene_vk_frame_acquire(size_t swapchain_handle) {
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)swapchain_handle;
    GrapheneVkFrame *frame = (GrapheneVkFrame *)calloc(1, sizeof(GrapheneVkFrame));
    if (frame == NULL) return 0;
    frame->owner = swapchain;
    if (swapchain == NULL || !swapchain->available || swapchain->frame_active) {
        strncpy(frame->error, "Swapchain cannot acquire another frame", sizeof(frame->error) - 1); return (size_t)frame;
    }
    GrapheneVkDevice *device = swapchain->owner;
    for (uint32_t attempt = 0; attempt < 2; ++attempt) {
        frame->frame_index = swapchain->frame_index;
        if (device->wait_for_fences(device->device, 1, &swapchain->fences[frame->frame_index], 1, UINT64_MAX) != VK_SUCCESS) {
            strncpy(frame->error, "Unable to wait for a frame fence", sizeof(frame->error) - 1); return (size_t)frame;
        }
        VkResult acquired = VK_SUCCESS;
        if (swapchain->offscreen) {
            frame->image_index = frame->frame_index;
        } else {
            acquired = swapchain->acquire_next_image(device->device, swapchain->swapchain, UINT64_MAX,
                swapchain->image_available[frame->frame_index], NULL, &frame->image_index);
        }
        if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: frame acquire=%d image=%u\n", acquired, frame->image_index);
        if (!swapchain->offscreen && acquired == VK_ERROR_OUT_OF_DATE_KHR) {
            if (!graphene_vk_swapchain_rebuild(swapchain)) {
                strncpy(frame->error, swapchain->error, sizeof(frame->error) - 1); return (size_t)frame;
            }
            continue;
        }
        if (acquired != VK_SUCCESS && acquired != VK_SUBOPTIMAL_KHR) {
            snprintf(frame->error, sizeof(frame->error), "Unable to acquire frame image (result %d)", acquired);
            return (size_t)frame;
        }
        frame->command_buffer = swapchain->command_buffers[frame->frame_index];
        if (device->reset_command_buffer(frame->command_buffer, 0) != VK_SUCCESS) {
            strncpy(frame->error, "Unable to reset frame command buffer", sizeof(frame->error) - 1); return (size_t)frame;
        }
        VkCommandBufferBeginInfo begin = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL,
            VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL};
        if (device->begin_command_buffer(frame->command_buffer, &begin) != VK_SUCCESS) {
            strncpy(frame->error, "Unable to begin frame command buffer", sizeof(frame->error) - 1); return (size_t)frame;
        }
        frame->recording = true;
        swapchain->frame_active = true;
        return (size_t)frame;
    }
    strncpy(frame->error, "Swapchain remained out of date after rebuild", sizeof(frame->error) - 1);
    return (size_t)frame;
}

bool graphene_vk_frame_available(size_t handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)handle;
    return frame != NULL && frame->recording && !frame->complete;
}

uint32_t graphene_vk_frame_slot(size_t handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)handle;
    return frame == NULL ? 0 : frame->frame_index;
}

encore_str graphene_vk_frame_error(size_t handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)handle;
    return graphene_string(frame == NULL ? "Invalid render frame" : frame->error);
}

bool graphene_vk_frame_begin_render_pass(size_t frame_handle, size_t pipeline_handle,
    float red, float green, float blue, float alpha) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    GrapheneVkPipeline *pipeline = (GrapheneVkPipeline *)pipeline_handle;
    if (frame == NULL || !frame->recording || frame->in_render_pass || pipeline == NULL ||
        !graphene_vk_swapchain_prepare_pipeline(frame->owner, pipeline)) {
        if (frame != NULL) strncpy(frame->error, "Unable to begin render pass", sizeof(frame->error) - 1);
        return false;
    }
    GrapheneVkSwapchain *swapchain = frame->owner;
    frame->pipeline = pipeline;
    VkClearValue clear_values[2] = {{{{red, green, blue, alpha}}}, {.depthStencil = {1.0f, 0}}};
    VkRenderPassBeginInfo render = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, NULL, pipeline->render_pass,
        swapchain->framebuffers[frame->image_index], {{0, 0}, {swapchain->width, swapchain->height}},
        pipeline->depth_test ? 2 : 1, clear_values};
    swapchain->cmd_begin_render_pass(frame->command_buffer, &render, VK_SUBPASS_CONTENTS_INLINE);
    swapchain->cmd_bind_pipeline(frame->command_buffer, VK_PIPELINE_BIND_POINT_GRAPHICS, pipeline->pipeline);
    VkViewport viewport = {0.0f, 0.0f, (float)swapchain->width, (float)swapchain->height, 0.0f, 1.0f};
    VkRect2D scissor = {{0, 0}, {swapchain->width, swapchain->height}};
    swapchain->cmd_set_viewport(frame->command_buffer, 0, 1, &viewport);
    swapchain->cmd_set_scissor(frame->command_buffer, 0, 1, &scissor);
    frame->in_render_pass = true;
    return true;
}

bool graphene_vk_frame_bind_group(size_t frame_handle, size_t bind_group_handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    GrapheneVkBindGroup *group = (GrapheneVkBindGroup *)bind_group_handle;
    if (frame == NULL || !frame->in_render_pass || frame->pipeline == NULL || group == NULL ||
        !group->available || group->owner != frame->owner->owner) return false;
    frame->owner->cmd_bind_descriptor_sets(frame->command_buffer, VK_PIPELINE_BIND_POINT_GRAPHICS,
        frame->pipeline->layout, 0, 1, &group->set, 0, NULL);
    return true;
}

bool graphene_vk_frame_bind_vertex_buffer(size_t frame_handle, size_t buffer_handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    if (frame == NULL || !frame->in_render_pass || buffer == NULL || !buffer->available ||
        buffer->owner != frame->owner->owner) return false;
    uint64_t offset = 0;
    frame->owner->cmd_bind_vertex_buffers(frame->command_buffer, 0, 1, &buffer->buffer, &offset);
    return true;
}

bool graphene_vk_frame_bind_index_buffer(size_t frame_handle, size_t buffer_handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    if (frame == NULL || !frame->in_render_pass || buffer == NULL || !buffer->available ||
        buffer->owner != frame->owner->owner) return false;
    frame->owner->cmd_bind_index_buffer(frame->command_buffer, buffer->buffer, 0, VK_INDEX_TYPE_UINT32);
    return true;
}

bool graphene_vk_frame_draw_indexed(size_t frame_handle, uint32_t index_count,
    uint32_t instance_count, uint32_t first_index, int32_t vertex_offset, uint32_t first_instance) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    if (frame == NULL || !frame->in_render_pass || index_count == 0 || instance_count == 0) return false;
    frame->owner->cmd_draw_indexed(frame->command_buffer, index_count, instance_count,
        first_index, vertex_offset, first_instance);
    return true;
}

bool graphene_vk_frame_end_render_pass(size_t frame_handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    if (frame == NULL || !frame->recording || !frame->in_render_pass) return false;
    frame->owner->cmd_end_render_pass(frame->command_buffer);
    frame->in_render_pass = false;
    return true;
}

bool graphene_vk_frame_set_viewport(size_t frame_handle, uint32_t x, uint32_t y,
    uint32_t width, uint32_t height) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    if (frame == NULL || !frame->in_render_pass || width == 0 || height == 0) return false;
    GrapheneVkSwapchain *swapchain = frame->owner;
    if (x >= swapchain->width || y >= swapchain->height) return false;
    if (width > swapchain->width - x) width = swapchain->width - x;
    if (height > swapchain->height - y) height = swapchain->height - y;
    VkViewport viewport = {(float)x, (float)y, (float)width, (float)height, 0.0f, 1.0f};
    VkRect2D scissor = {{(int32_t)x, (int32_t)y}, {width, height}};
    swapchain->cmd_set_viewport(frame->command_buffer, 0, 1, &viewport);
    swapchain->cmd_set_scissor(frame->command_buffer, 0, 1, &scissor);
    return true;
}

static void graphene_vk_copy_ui_region(GrapheneVkFrame *frame,
    void *staging_buffer, uint32_t x, uint32_t y, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0) return;
    GrapheneVkSwapchain *swapchain = frame->owner;
    VkBufferImageCopy region = {
        (uint64_t)y * swapchain->readback_pitch + (uint64_t)x * 4u,
        swapchain->width, swapchain->height,
        {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
        {(int32_t)x, (int32_t)y, 0}, {width, height, 1}
    };
    swapchain->owner->cmd_copy_buffer_to_image(frame->command_buffer, staging_buffer,
        swapchain->images[frame->image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
}

static void graphene_vk_stage_ui_region(GrapheneVkSwapchain *swapchain,
    unsigned char *destination, const unsigned char *source, uint32_t source_pitch,
    uint32_t x, uint32_t y, uint32_t width, uint32_t height) {
    if (width == 0 || height == 0) return;
    for (uint32_t row = y; row < y + height; ++row) {
        memcpy(destination + (size_t)row * swapchain->readback_pitch + (size_t)x * 4u,
            source + (size_t)row * source_pitch + (size_t)x * 4u, (size_t)width * 4u);
    }
}

bool graphene_vk_frame_upload_ui(size_t frame_handle, size_t pixels_handle,
    uint32_t width, uint32_t height, uint32_t pitch,
    uint32_t hole_x, uint32_t hole_y, uint32_t hole_width, uint32_t hole_height) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    if (frame == NULL || !frame->recording || frame->in_render_pass || frame->complete ||
        frame->owner->offscreen || frame->owner->readback_pixels == NULL || pixels_handle == 0 ||
        width == 0 || height == 0 || pitch < width * 4u) {
        if (graphene_vk_trace_enabled()) fprintf(stderr,
            "graphene-vk: UI upload rejected surface=%ux%u pitch=%u swapchain=%ux%u recording=%d pass=%d\n",
            width, height, pitch, frame == NULL ? 0 : frame->owner->width,
            frame == NULL ? 0 : frame->owner->height, frame == NULL ? 0 : frame->recording,
            frame == NULL ? 0 : frame->in_render_pass);
        return false;
    }
    GrapheneVkSwapchain *swapchain = frame->owner;
    const unsigned char *source = (const unsigned char *)(uintptr_t)pixels_handle;
    void *staging_buffer = frame->frame_index == 0 ? swapchain->readback_buffer : swapchain->ui_staging_buffer;
    unsigned char *destination = (unsigned char *)(frame->frame_index == 0
        ? swapchain->readback_pixels : swapchain->ui_staging_pixels);
    if (staging_buffer == NULL || destination == NULL) return false;
    bool matching_extent = width == swapchain->width && height == swapchain->height;
    if (!matching_extent) {
        for (uint32_t row = 0; row < swapchain->height; ++row) {
            uint32_t source_y = (uint32_t)(((uint64_t)row * height) / swapchain->height);
            for (uint32_t column = 0; column < swapchain->width; ++column) {
                uint32_t source_x = (uint32_t)(((uint64_t)column * width) / swapchain->width);
                memcpy(destination + (size_t)row * swapchain->readback_pitch + (size_t)column * 4u,
                    source + (size_t)source_y * pitch + (size_t)source_x * 4u, 4u);
            }
        }
        hole_x = (uint32_t)(((uint64_t)hole_x * swapchain->width) / width);
        hole_y = (uint32_t)(((uint64_t)hole_y * swapchain->height) / height);
        hole_width = (uint32_t)(((uint64_t)hole_width * swapchain->width) / width);
        hole_height = (uint32_t)(((uint64_t)hole_height * swapchain->height) / height);
    }
    width = swapchain->width;
    height = swapchain->height;
    if (hole_x > width) hole_x = width;
    if (hole_y > height) hole_y = height;
    if (hole_width > width - hole_x) hole_width = width - hole_x;
    if (hole_height > height - hole_y) hole_height = height - hole_y;
    uint32_t hole_right = hole_x + hole_width;
    uint32_t hole_bottom = hole_y + hole_height;
    if (matching_extent) {
        graphene_vk_stage_ui_region(swapchain, destination, source, pitch, 0, 0, width, hole_y);
        graphene_vk_stage_ui_region(swapchain, destination, source, pitch, 0, hole_bottom, width, height - hole_bottom);
        graphene_vk_stage_ui_region(swapchain, destination, source, pitch, 0, hole_y, hole_x, hole_height);
        graphene_vk_stage_ui_region(swapchain, destination, source, pitch, hole_right, hole_y,
            width - hole_right, hole_height);
    }
    VkImageMemoryBarrier to_copy = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL,
        VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, VK_ACCESS_TRANSFER_WRITE_BIT,
        VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED, swapchain->images[frame->image_index],
        {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    swapchain->owner->cmd_pipeline_barrier(frame->command_buffer, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &to_copy);
    graphene_vk_copy_ui_region(frame, staging_buffer, 0, 0, width, hole_y);
    graphene_vk_copy_ui_region(frame, staging_buffer, 0, hole_bottom, width, height - hole_bottom);
    graphene_vk_copy_ui_region(frame, staging_buffer, 0, hole_y, hole_x, hole_height);
    graphene_vk_copy_ui_region(frame, staging_buffer, hole_right, hole_y, width - hole_right, hole_height);
    VkImageMemoryBarrier to_present = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL,
        VK_ACCESS_TRANSFER_WRITE_BIT, 0, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
        VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
        swapchain->images[frame->image_index], {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    swapchain->owner->cmd_pipeline_barrier(frame->command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, NULL, 0, NULL, 1, &to_present);
    return true;
}

bool graphene_vk_frame_present(size_t frame_handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)frame_handle;
    if (frame == NULL || !frame->recording || frame->in_render_pass || frame->complete) return false;
    GrapheneVkSwapchain *swapchain = frame->owner;
    GrapheneVkDevice *device = swapchain->owner;
    if (swapchain->offscreen) {
        VkImageMemoryBarrier to_transfer = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL,
            VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, VK_ACCESS_TRANSFER_READ_BIT,
            VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED, swapchain->images[frame->image_index],
            {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        device->cmd_pipeline_barrier(frame->command_buffer, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &to_transfer);
        VkBufferImageCopy copy = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            {0, 0, 0}, {swapchain->width, swapchain->height, 1}};
        device->cmd_copy_image_to_buffer(frame->command_buffer, swapchain->images[frame->image_index],
            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, swapchain->readback_buffer, 1, &copy);
        VkImageMemoryBarrier restore = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL,
            VK_ACCESS_TRANSFER_READ_BIT, 0, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
            swapchain->images[frame->image_index], {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
        device->cmd_pipeline_barrier(frame->command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 0, NULL, 0, NULL, 1, &restore);
    }
    if (device->end_command_buffer(frame->command_buffer) != VK_SUCCESS ||
        swapchain->reset_fences(device->device, 1, &swapchain->fences[frame->frame_index]) != VK_SUCCESS) {
        strncpy(frame->error, "Unable to finalize frame commands", sizeof(frame->error) - 1); return false;
    }
    uint32_t wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submit = {VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL,
        swapchain->offscreen ? 0 : 1,
        swapchain->offscreen ? NULL : &swapchain->image_available[frame->frame_index],
        swapchain->offscreen ? NULL : &wait_stage, 1, &frame->command_buffer,
        swapchain->offscreen ? 0 : 1,
        swapchain->offscreen ? NULL : &swapchain->render_finished[frame->frame_index]};
    if (device->queue_submit(device->queue, 1, &submit, swapchain->fences[frame->frame_index]) != VK_SUCCESS) {
        strncpy(frame->error, "Unable to submit render frame", sizeof(frame->error) - 1); return false;
    }
    if (swapchain->offscreen &&
        device->wait_for_fences(device->device, 1, &swapchain->fences[frame->frame_index], 1, UINT64_MAX) != VK_SUCCESS) {
        strncpy(frame->error, "Unable to complete offscreen render frame", sizeof(frame->error) - 1); return false;
    }
    VkResult status = VK_SUCCESS;
    if (!swapchain->offscreen) {
        VkPresentInfoKHR present = {VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, NULL, 1,
            &swapchain->render_finished[frame->frame_index], 1, &swapchain->swapchain, &frame->image_index, NULL};
        status = swapchain->queue_present(device->queue, &present);
    }
    if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: frame present=%d\n", status);
    swapchain->frame_index = (frame->frame_index + 1) % 2;
    swapchain->frame_active = false;
    frame->recording = false;
    frame->complete = true;
    if (!swapchain->offscreen && (status == VK_ERROR_OUT_OF_DATE_KHR || status == VK_SUBOPTIMAL_KHR)) {
        graphene_vk_swapchain_rebuild(swapchain);
        strncpy(frame->error, "Swapchain was rebuilt; frame must be redrawn", sizeof(frame->error) - 1);
        return false;
    }
    if (status != VK_SUCCESS) {
        snprintf(frame->error, sizeof(frame->error), "Unable to present render frame (result %d)", status); return false;
    }
    return true;
}

size_t graphene_vk_swapchain_pixels(size_t handle) {
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)handle;
    if (swapchain == NULL || !swapchain->available || swapchain->readback_pixels == NULL) return 0;
    if (!swapchain->offscreen && swapchain->owner->queue_wait_idle(swapchain->owner->queue) != VK_SUCCESS) return 0;
    return (size_t)swapchain->readback_pixels;
}

uint32_t graphene_vk_swapchain_pitch(size_t handle) {
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)handle;
    return swapchain == NULL ? 0 : swapchain->readback_pitch;
}

bool graphene_vk_frame_destroy(size_t handle) {
    GrapheneVkFrame *frame = (GrapheneVkFrame *)handle;
    if (frame == NULL) return false;
    if (frame->recording && frame->owner != NULL) {
        if (frame->in_render_pass) graphene_vk_frame_end_render_pass(handle);
        graphene_vk_frame_present(handle);
    }
    free(frame); return true;
}

static bool graphene_vk_swapchain_draw_internal(size_t handle, GrapheneVkPipeline *render_pipeline,
    GrapheneVkBuffer *vertex_buffer, GrapheneVkBuffer *index_buffer, GrapheneVkBindGroup *bind_group,
    uint32_t index_count,
    float red, float green, float blue, float alpha, bool triangle) {
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)handle;
    if (swapchain == NULL || !swapchain->available) return false;
    GrapheneVkDevice *device = swapchain->owner;
    if (render_pipeline != NULL && !graphene_vk_swapchain_prepare_pipeline(swapchain, render_pipeline)) return false;
    if ((vertex_buffer != NULL || index_buffer != NULL) &&
        (vertex_buffer == NULL || index_buffer == NULL || !vertex_buffer->available || !index_buffer->available ||
        vertex_buffer->owner != device || index_buffer->owner != device || index_count == 0)) {
        strncpy(swapchain->error, "Invalid indexed draw buffers", sizeof(swapchain->error) - 1); return false;
    }
    if (bind_group != NULL && (!bind_group->available || bind_group->owner != device)) {
        strncpy(swapchain->error, "Invalid draw bind group", sizeof(swapchain->error) - 1); return false;
    }
    uint32_t frame = swapchain->frame_index;
    if (device->wait_for_fences(device->device, 1, &swapchain->fences[frame], 1, UINT64_MAX) != VK_SUCCESS) {
        strncpy(swapchain->error, "Unable to wait for a frame fence", sizeof(swapchain->error) - 1); return false;
    }
    uint32_t image_index = 0;
    VkResult acquired = swapchain->acquire_next_image(device->device, swapchain->swapchain, UINT64_MAX,
        swapchain->image_available[frame], NULL, &image_index);
    if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: acquire=%d image=%u\n", acquired, image_index);
    if (acquired == VK_ERROR_OUT_OF_DATE_KHR) return graphene_vk_swapchain_rebuild(swapchain);
    if (acquired != VK_SUCCESS && acquired != VK_SUBOPTIMAL_KHR) {
        strncpy(swapchain->error, "Unable to acquire the next swapchain image", sizeof(swapchain->error) - 1); return false;
    }
    void *command = swapchain->command_buffers[frame];
    if (device->reset_command_buffer(command, 0) != VK_SUCCESS ||
        swapchain->reset_fences(device->device, 1, &swapchain->fences[frame]) != VK_SUCCESS) {
        strncpy(swapchain->error, "Unable to reset Vulkan frame resources", sizeof(swapchain->error) - 1); return false;
    }
    VkCommandBufferBeginInfo begin = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL};
    if (device->begin_command_buffer(command, &begin) != VK_SUCCESS) {
        strncpy(swapchain->error, "Unable to begin a frame command buffer", sizeof(swapchain->error) - 1); return false;
    }
    if (triangle) {
        VkClearValue clear_value = {{{red, green, blue, alpha}}};
        VkRenderPassBeginInfo render = {VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, NULL, render_pipeline->render_pass,
            swapchain->framebuffers[image_index], {{0, 0}, {swapchain->width, swapchain->height}}, 1, &clear_value};
        swapchain->cmd_begin_render_pass(command, &render, VK_SUBPASS_CONTENTS_INLINE);
        swapchain->cmd_bind_pipeline(command, VK_PIPELINE_BIND_POINT_GRAPHICS, render_pipeline->pipeline);
        VkViewport viewport = {0.0f, 0.0f, (float)swapchain->width, (float)swapchain->height, 0.0f, 1.0f};
        VkRect2D scissor = {{0, 0}, {swapchain->width, swapchain->height}};
        swapchain->cmd_set_viewport(command, 0, 1, &viewport);
        swapchain->cmd_set_scissor(command, 0, 1, &scissor);
        if (bind_group != NULL)
            swapchain->cmd_bind_descriptor_sets(command, VK_PIPELINE_BIND_POINT_GRAPHICS, render_pipeline->layout,
                0, 1, &bind_group->set, 0, NULL);
        if (vertex_buffer != NULL) {
            uint64_t vertex_offset = 0;
            swapchain->cmd_bind_vertex_buffers(command, 0, 1, &vertex_buffer->buffer, &vertex_offset);
            swapchain->cmd_bind_index_buffer(command, index_buffer->buffer, 0, VK_INDEX_TYPE_UINT32);
            swapchain->cmd_draw_indexed(command, index_count, 1, 0, 0, 0);
        } else {
            swapchain->cmd_draw(command, 3, 1, 0, 0);
        }
        swapchain->cmd_end_render_pass(command);
    } else {
        VkImageSubresourceRange range = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
        VkImageMemoryBarrier to_transfer = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL, 0, VK_ACCESS_TRANSFER_WRITE_BIT,
            VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
            swapchain->images[image_index], range};
        device->cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, NULL, 0, NULL, 1, &to_transfer);
        VkClearColorValue color = {{red, green, blue, alpha}};
        swapchain->cmd_clear_color_image(command, swapchain->images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &color, 1, &range);
        VkImageMemoryBarrier to_present = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL, VK_ACCESS_TRANSFER_WRITE_BIT, 0,
            VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
            swapchain->images[image_index], range};
        device->cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            0, 0, NULL, 0, NULL, 1, &to_present);
    }
    if (device->end_command_buffer(command) != VK_SUCCESS) {
        strncpy(swapchain->error, "Unable to end a frame command buffer", sizeof(swapchain->error) - 1); return false;
    }
    uint32_t wait_stage = triangle ? VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT : VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo submit = {VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL, 1, &swapchain->image_available[frame], &wait_stage,
        1, &command, 1, &swapchain->render_finished[frame]};
    if (device->queue_submit(device->queue, 1, &submit, swapchain->fences[frame]) != VK_SUCCESS) {
        strncpy(swapchain->error, "Unable to submit a frame", sizeof(swapchain->error) - 1); return false;
    }
    VkPresentInfoKHR present = {VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, NULL, 1, &swapchain->render_finished[frame],
        1, &swapchain->swapchain, &image_index, NULL};
    VkResult status = swapchain->queue_present(device->queue, &present);
    if (graphene_vk_trace_enabled()) fprintf(stderr, "graphene-vk: present=%d\n", status);
    swapchain->frame_index = (frame + 1) % 2;
    if (status == VK_ERROR_OUT_OF_DATE_KHR || status == VK_SUBOPTIMAL_KHR || acquired == VK_SUBOPTIMAL_KHR)
        return graphene_vk_swapchain_rebuild(swapchain);
    if (status != VK_SUCCESS && status != VK_SUBOPTIMAL_KHR)
        snprintf(swapchain->error, sizeof(swapchain->error), "Unable to present a frame (Vulkan result %d)", status);
    return status == VK_SUCCESS || status == VK_SUBOPTIMAL_KHR;
}

bool graphene_vk_swapchain_clear(size_t handle, float red, float green, float blue, float alpha) {
    return graphene_vk_swapchain_draw_internal(handle, NULL, NULL, NULL, NULL, 0, red, green, blue, alpha, false);
}

bool graphene_vk_swapchain_draw_pipeline(size_t handle, size_t pipeline_handle,
    float red, float green, float blue, float alpha) {
    return graphene_vk_swapchain_draw_internal(handle, (GrapheneVkPipeline *)pipeline_handle,
        NULL, NULL, NULL, 0, red, green, blue, alpha, true);
}

bool graphene_vk_swapchain_draw_indexed(size_t handle, size_t pipeline_handle, size_t vertex_handle,
    size_t index_handle, uint32_t index_count, float red, float green, float blue, float alpha) {
    return graphene_vk_swapchain_draw_internal(handle, (GrapheneVkPipeline *)pipeline_handle,
        (GrapheneVkBuffer *)vertex_handle, (GrapheneVkBuffer *)index_handle, NULL, index_count,
        red, green, blue, alpha, true);
}

bool graphene_vk_swapchain_draw_indexed_bound(size_t handle, size_t pipeline_handle, size_t vertex_handle,
    size_t index_handle, size_t bind_group_handle, uint32_t index_count,
    float red, float green, float blue, float alpha) {
    return graphene_vk_swapchain_draw_internal(handle, (GrapheneVkPipeline *)pipeline_handle,
        (GrapheneVkBuffer *)vertex_handle, (GrapheneVkBuffer *)index_handle,
        (GrapheneVkBindGroup *)bind_group_handle, index_count, red, green, blue, alpha, true);
}

bool graphene_vk_swapchain_destroy(size_t handle) {
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)handle;
    if (swapchain == NULL) return false;
    GrapheneVkDevice *device = swapchain->owner;
    if (device != NULL && device->device != NULL) {
        device->queue_wait_idle(device->queue);
        if (swapchain->command_buffers[0] != NULL)
            device->free_command_buffers(device->device, device->command_pool, 2, swapchain->command_buffers);
        for (uint32_t frame = 0; frame < 2; ++frame) {
            if (swapchain->image_available[frame] != NULL) swapchain->destroy_semaphore(device->device, swapchain->image_available[frame], NULL);
            if (swapchain->render_finished[frame] != NULL) swapchain->destroy_semaphore(device->device, swapchain->render_finished[frame], NULL);
            if (swapchain->fences[frame] != NULL) device->destroy_fence(device->device, swapchain->fences[frame], NULL);
        }
        graphene_vk_swapchain_release_render_resources(swapchain);
        graphene_vk_swapchain_release_readback(swapchain);
        if (swapchain->swapchain != 0) swapchain->destroy_swapchain(device->device, swapchain->swapchain, NULL);
    }
    free(swapchain->images); free(swapchain); return true;
}
bool graphene_vk_swapchain_available(size_t handle) { GrapheneVkSwapchain *s = (GrapheneVkSwapchain *)handle; return s != NULL && s->available; }
encore_str graphene_vk_swapchain_error(size_t handle) { GrapheneVkSwapchain *s = (GrapheneVkSwapchain *)handle; return graphene_string(s == NULL ? "Invalid swapchain" : s->error); }
uint32_t graphene_vk_swapchain_width(size_t handle) { GrapheneVkSwapchain *s = (GrapheneVkSwapchain *)handle; return s == NULL ? 0 : s->width; }
uint32_t graphene_vk_swapchain_height(size_t handle) { GrapheneVkSwapchain *s = (GrapheneVkSwapchain *)handle; return s == NULL ? 0 : s->height; }
uint32_t graphene_vk_swapchain_frames_in_flight(size_t handle) { return handle == 0 ? 0 : 2; }
