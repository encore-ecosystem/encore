/* Logical devices, shaders, bindings, samplers and graphics pipelines. */
static size_t graphene_vk_device_create_internal(size_t context_handle, size_t adapter_index, VkSurfaceKHR surface) {
    GrapheneVkContext *context = (GrapheneVkContext *)context_handle;
    GrapheneVkDevice *result = (GrapheneVkDevice *)calloc(1, sizeof(GrapheneVkDevice));
    if (result == NULL) return 0;
    GrapheneVkAdapter *adapter = graphene_adapter(context_handle, adapter_index);
    if (context == NULL || !context->available || adapter == NULL) {
        strncpy(result->error, "Invalid Vulkan adapter", sizeof(result->error) - 1); return (size_t)result;
    }
    result->context = context;
    result->physical_device = adapter->handle;
    if (adapter->api_version < graphene_vk_version(1, 2, 0)) {
        strncpy(result->error, "Graphene requires Vulkan 1.2 or newer", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkGetPhysicalDeviceQueueFamilyProperties get_queue_properties =
        (PFN_vkGetPhysicalDeviceQueueFamilyProperties)context->get_proc(context->instance, "vkGetPhysicalDeviceQueueFamilyProperties");
    PFN_vkCreateDevice create_device =
        (PFN_vkCreateDevice)context->get_proc(context->instance, "vkCreateDevice");
    PFN_vkGetDeviceProcAddr get_device_proc =
        (PFN_vkGetDeviceProcAddr)context->get_proc(context->instance, "vkGetDeviceProcAddr");
    if (get_queue_properties == NULL || create_device == NULL || get_device_proc == NULL) {
        strncpy(result->error, "Required Vulkan device functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    result->get_device_proc = get_device_proc;
    PFN_vkGetPhysicalDeviceMemoryProperties get_memory_properties =
        (PFN_vkGetPhysicalDeviceMemoryProperties)context->get_proc(context->instance, "vkGetPhysicalDeviceMemoryProperties");
    if (get_memory_properties == NULL) {
        strncpy(result->error, "vkGetPhysicalDeviceMemoryProperties was not found", sizeof(result->error) - 1); return (size_t)result;
    }
    get_memory_properties(adapter->handle, &result->memory_properties);
    uint32_t count = 0;
    get_queue_properties(adapter->handle, &count, NULL);
    if (count == 0) { strncpy(result->error, "Adapter has no queue families", sizeof(result->error) - 1); return (size_t)result; }
    VkQueueFamilyProperties *families = (VkQueueFamilyProperties *)calloc(count, sizeof(VkQueueFamilyProperties));
    if (families == NULL) { strncpy(result->error, "Unable to allocate queue family data", sizeof(result->error) - 1); return (size_t)result; }
    get_queue_properties(adapter->handle, &count, families);
    PFN_vkGetPhysicalDeviceSurfaceSupportKHR get_surface_support = NULL;
    if (surface != 0) {
        get_surface_support = (PFN_vkGetPhysicalDeviceSurfaceSupportKHR)context->get_proc(
            context->instance, "vkGetPhysicalDeviceSurfaceSupportKHR");
        if (get_surface_support == NULL) {
            free(families); strncpy(result->error, "Vulkan surface support query was not found", sizeof(result->error) - 1); return (size_t)result;
        }
    }
    uint32_t selected = UINT32_MAX;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t present = 0;
        if (surface != 0 && get_surface_support(adapter->handle, i, surface, &present) != VK_SUCCESS) present = 0;
        if (families[i].queueCount > 0 && (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) != 0 &&
            (families[i].queueFlags & VK_QUEUE_COMPUTE_BIT) != 0 && (surface == 0 || present != 0)) { selected = i; break; }
    }
    if (selected == UINT32_MAX) {
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t present = 0;
            if (surface != 0 && get_surface_support(adapter->handle, i, surface, &present) != VK_SUCCESS) present = 0;
            if (families[i].queueCount > 0 && (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) != 0 &&
                (surface == 0 || present != 0)) { selected = i; break; }
        }
    }
    if (selected == UINT32_MAX) {
        free(families); strncpy(result->error, surface == 0 ? "Adapter has no graphics queue" :
            "Adapter has no graphics queue with present support", sizeof(result->error) - 1); return (size_t)result;
    }
    result->queue_family = selected;
    result->queue_flags = families[selected].queueFlags;
    result->present = surface != 0;
    free(families);
    float priority = 1.0f;
    VkDeviceQueueCreateInfo queue_info = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, NULL, 0, selected, 1, &priority};
    const char *swapchain_extensions[1] = {"VK_KHR_swapchain"};
    VkDeviceCreateInfo device_info = {VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, NULL, 0, 1, &queue_info, 0, NULL,
        surface == 0 ? 0 : 1, surface == 0 ? NULL : swapchain_extensions, NULL};
    VkResult status = create_device(adapter->handle, &device_info, NULL, &result->device);
    if (status != VK_SUCCESS) { strncpy(result->error, "Unable to create Vulkan logical device", sizeof(result->error) - 1); return (size_t)result; }
    result->destroy_device = (PFN_vkDestroyDevice)get_device_proc(result->device, "vkDestroyDevice");
    PFN_vkGetDeviceQueue get_queue = (PFN_vkGetDeviceQueue)get_device_proc(result->device, "vkGetDeviceQueue");
    if (result->destroy_device == NULL || get_queue == NULL) {
        strncpy(result->error, "Required Vulkan queue functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    get_queue(result->device, selected, 0, &result->queue);
    if (result->queue == NULL) { strncpy(result->error, "Unable to acquire Vulkan graphics queue", sizeof(result->error) - 1); return (size_t)result; }
    PFN_vkCreateCommandPool create_command_pool =
        (PFN_vkCreateCommandPool)get_device_proc(result->device, "vkCreateCommandPool");
    result->destroy_command_pool = (PFN_vkDestroyCommandPool)get_device_proc(result->device, "vkDestroyCommandPool");
    result->allocate_command_buffers = (PFN_vkAllocateCommandBuffers)get_device_proc(result->device, "vkAllocateCommandBuffers");
    result->free_command_buffers = (PFN_vkFreeCommandBuffers)get_device_proc(result->device, "vkFreeCommandBuffers");
    result->begin_command_buffer = (PFN_vkBeginCommandBuffer)get_device_proc(result->device, "vkBeginCommandBuffer");
    result->end_command_buffer = (PFN_vkEndCommandBuffer)get_device_proc(result->device, "vkEndCommandBuffer");
    result->reset_command_buffer = (PFN_vkResetCommandBuffer)get_device_proc(result->device, "vkResetCommandBuffer");
    result->queue_submit = (PFN_vkQueueSubmit)get_device_proc(result->device, "vkQueueSubmit");
    result->queue_wait_idle = (PFN_vkQueueWaitIdle)get_device_proc(result->device, "vkQueueWaitIdle");
    result->create_buffer = (PFN_vkCreateBuffer)get_device_proc(result->device, "vkCreateBuffer");
    result->destroy_buffer = (PFN_vkDestroyBuffer)get_device_proc(result->device, "vkDestroyBuffer");
    result->get_buffer_requirements = (PFN_vkGetBufferMemoryRequirements)get_device_proc(result->device, "vkGetBufferMemoryRequirements");
    result->allocate_memory = (PFN_vkAllocateMemory)get_device_proc(result->device, "vkAllocateMemory");
    result->free_memory = (PFN_vkFreeMemory)get_device_proc(result->device, "vkFreeMemory");
    result->bind_buffer_memory = (PFN_vkBindBufferMemory)get_device_proc(result->device, "vkBindBufferMemory");
    result->map_memory = (PFN_vkMapMemory)get_device_proc(result->device, "vkMapMemory");
    result->unmap_memory = (PFN_vkUnmapMemory)get_device_proc(result->device, "vkUnmapMemory");
    result->create_image = (PFN_vkCreateImage)get_device_proc(result->device, "vkCreateImage");
    result->destroy_image = (PFN_vkDestroyImage)get_device_proc(result->device, "vkDestroyImage");
    result->get_image_requirements = (PFN_vkGetImageMemoryRequirements)get_device_proc(result->device, "vkGetImageMemoryRequirements");
    result->bind_image_memory = (PFN_vkBindImageMemory)get_device_proc(result->device, "vkBindImageMemory");
    result->create_image_view = (PFN_vkCreateImageView)get_device_proc(result->device, "vkCreateImageView");
    result->destroy_image_view = (PFN_vkDestroyImageView)get_device_proc(result->device, "vkDestroyImageView");
    result->cmd_pipeline_barrier = (PFN_vkCmdPipelineBarrier)get_device_proc(result->device, "vkCmdPipelineBarrier");
    result->cmd_copy_buffer_to_image = (PFN_vkCmdCopyBufferToImage)get_device_proc(result->device, "vkCmdCopyBufferToImage");
    result->cmd_copy_image_to_buffer = (PFN_vkCmdCopyImageToBuffer)get_device_proc(result->device, "vkCmdCopyImageToBuffer");
    result->cmd_copy_buffer = (PFN_vkCmdCopyBuffer)get_device_proc(result->device, "vkCmdCopyBuffer");
    result->cmd_bind_pipeline = (PFN_vkCmdBindPipeline)get_device_proc(result->device, "vkCmdBindPipeline");
    result->cmd_bind_descriptor_sets = (PFN_vkCmdBindDescriptorSets)get_device_proc(result->device, "vkCmdBindDescriptorSets");
    result->cmd_dispatch = (PFN_vkCmdDispatch)get_device_proc(result->device, "vkCmdDispatch");
    result->create_fence = (PFN_vkCreateFence)get_device_proc(result->device, "vkCreateFence");
    result->destroy_fence = (PFN_vkDestroyFence)get_device_proc(result->device, "vkDestroyFence");
    result->get_fence_status = (PFN_vkGetFenceStatus)get_device_proc(result->device, "vkGetFenceStatus");
    result->wait_for_fences = (PFN_vkWaitForFences)get_device_proc(result->device, "vkWaitForFences");
    if (create_command_pool == NULL || result->destroy_command_pool == NULL || result->allocate_command_buffers == NULL ||
        result->free_command_buffers == NULL || result->begin_command_buffer == NULL || result->end_command_buffer == NULL ||
        result->reset_command_buffer == NULL ||
        result->queue_submit == NULL || result->queue_wait_idle == NULL || result->create_buffer == NULL ||
        result->destroy_buffer == NULL || result->get_buffer_requirements == NULL || result->allocate_memory == NULL ||
        result->free_memory == NULL || result->bind_buffer_memory == NULL || result->map_memory == NULL || result->unmap_memory == NULL ||
        result->create_image == NULL || result->destroy_image == NULL || result->get_image_requirements == NULL || result->bind_image_memory == NULL ||
        result->create_image_view == NULL || result->destroy_image_view == NULL || result->cmd_pipeline_barrier == NULL ||
        result->cmd_copy_buffer_to_image == NULL || result->cmd_copy_image_to_buffer == NULL ||
        result->cmd_copy_buffer == NULL || result->cmd_bind_pipeline == NULL ||
        result->cmd_bind_descriptor_sets == NULL || result->cmd_dispatch == NULL ||
        result->create_fence == NULL || result->destroy_fence == NULL || result->get_fence_status == NULL || result->wait_for_fences == NULL) {
        strncpy(result->error, "Required Vulkan command functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkCommandPoolCreateInfo pool_info = {
        VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL,
        VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, selected
    };
    if (create_command_pool(result->device, &pool_info, NULL, &result->command_pool) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create Vulkan command pool", sizeof(result->error) - 1); return (size_t)result;
    }
    result->available = true;
    return (size_t)result;
}

size_t graphene_vk_device_create(size_t context_handle, size_t adapter_index) {
    return graphene_vk_device_create_internal(context_handle, adapter_index, 0);
}

size_t graphene_vk_present_device_create(size_t context_handle, size_t adapter_index, size_t window_handle) {
    GrapheneVkWindow *window = (GrapheneVkWindow *)window_handle;
    if (window == NULL || window->owner != (GrapheneVkContext *)context_handle || window->surface == 0) {
        GrapheneVkDevice *result = (GrapheneVkDevice *)calloc(1, sizeof(GrapheneVkDevice));
        if (result != NULL) strncpy(result->error, "Invalid Graphene presentation window", sizeof(result->error) - 1);
        return (size_t)result;
    }
    return graphene_vk_device_create_internal(context_handle, adapter_index, window->surface);
}

bool graphene_vk_device_destroy(size_t handle) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)handle;
    if (device == NULL) return false;
    if (device->device != NULL && device->command_pool != NULL && device->destroy_command_pool != NULL)
        device->destroy_command_pool(device->device, device->command_pool, NULL);
    if (device->device != NULL && device->destroy_device != NULL) device->destroy_device(device->device, NULL);
    free(device);
    return true;
}

bool graphene_vk_device_available(size_t handle) { GrapheneVkDevice *d = (GrapheneVkDevice *)handle; return d != NULL && d->available; }
encore_str graphene_vk_device_error(size_t handle) { GrapheneVkDevice *d = (GrapheneVkDevice *)handle; return graphene_string(d == NULL ? "Invalid Vulkan device" : d->error); }
uint32_t graphene_vk_device_queue_family(size_t handle) { GrapheneVkDevice *d = (GrapheneVkDevice *)handle; return d == NULL ? 0 : d->queue_family; }
bool graphene_vk_device_graphics(size_t handle) { GrapheneVkDevice *d = (GrapheneVkDevice *)handle; return d != NULL && (d->queue_flags & VK_QUEUE_GRAPHICS_BIT) != 0; }
bool graphene_vk_device_compute(size_t handle) { GrapheneVkDevice *d = (GrapheneVkDevice *)handle; return d != NULL && (d->queue_flags & VK_QUEUE_COMPUTE_BIT) != 0; }

size_t graphene_vk_shader_create(size_t device_handle, const uint32_t *words, size_t word_count, size_t capacity, uint32_t stage) {
    (void)capacity;
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkShader *shader = (GrapheneVkShader *)calloc(1, sizeof(GrapheneVkShader));
    if (shader == NULL) return 0;
    shader->owner = device;
    shader->stage = stage;
    if (device == NULL || !device->available || words == NULL || word_count == 0 ||
        (stage != VK_SHADER_STAGE_VERTEX_BIT && stage != VK_SHADER_STAGE_FRAGMENT_BIT && stage != VK_SHADER_STAGE_COMPUTE_BIT)) {
        strncpy(shader->error, "Invalid SPIR-V shader input", sizeof(shader->error) - 1); return (size_t)shader;
    }
    PFN_vkCreateShaderModule create_shader_module =
        (PFN_vkCreateShaderModule)device->get_device_proc(device->device, "vkCreateShaderModule");
    shader->destroy_shader_module =
        (PFN_vkDestroyShaderModule)device->get_device_proc(device->device, "vkDestroyShaderModule");
    if (create_shader_module == NULL || shader->destroy_shader_module == NULL) {
        strncpy(shader->error, "Vulkan shader module functions were not found", sizeof(shader->error) - 1); return (size_t)shader;
    }
    VkShaderModuleCreateInfo info = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0,
        word_count * sizeof(uint32_t), words};
    VkResult status = create_shader_module(device->device, &info, NULL, &shader->module);
    if (status != VK_SUCCESS) {
        snprintf(shader->error, sizeof(shader->error), "Unable to create Vulkan shader module (result %d)", status);
        return (size_t)shader;
    }
    shader->available = true;
    return (size_t)shader;
}

bool graphene_vk_shader_available(size_t handle) { GrapheneVkShader *s = (GrapheneVkShader *)handle; return s != NULL && s->available; }
encore_str graphene_vk_shader_error(size_t handle) { GrapheneVkShader *s = (GrapheneVkShader *)handle; return graphene_string(s == NULL ? "Invalid shader module" : s->error); }
uint32_t graphene_vk_shader_stage(size_t handle) { GrapheneVkShader *s = (GrapheneVkShader *)handle; return s == NULL ? 0 : s->stage; }
bool graphene_vk_shader_destroy(size_t handle) {
    GrapheneVkShader *shader = (GrapheneVkShader *)handle;
    if (shader == NULL) return false;
    if (shader->module != NULL && shader->owner != NULL && shader->owner->device != NULL && shader->destroy_shader_module != NULL)
        shader->destroy_shader_module(shader->owner->device, shader->module, NULL);
    free(shader);
    return true;
}

size_t graphene_vk_bind_group_layout_create_entries(size_t device_handle,
    const uint32_t *bindings, size_t binding_count, size_t binding_capacity,
    const uint32_t *types, size_t type_count, size_t type_capacity,
    const uint32_t *stages, size_t stage_count, size_t stage_capacity) {
    (void)binding_capacity; (void)type_capacity; (void)stage_capacity;
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkBindGroupLayout *result = (GrapheneVkBindGroupLayout *)calloc(1, sizeof(GrapheneVkBindGroupLayout));
    if (result == NULL) return 0;
    result->owner = device;
    if (device == NULL || !device->available || binding_count == 0 || binding_count > 16 ||
        binding_count != type_count || binding_count != stage_count) {
        strncpy(result->error, "Invalid bind group layout", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateDescriptorSetLayout create_layout =
        (PFN_vkCreateDescriptorSetLayout)device->get_device_proc(device->device, "vkCreateDescriptorSetLayout");
    result->destroy_layout =
        (PFN_vkDestroyDescriptorSetLayout)device->get_device_proc(device->device, "vkDestroyDescriptorSetLayout");
    if (create_layout == NULL || result->destroy_layout == NULL) {
        strncpy(result->error, "Vulkan descriptor layout functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorSetLayoutBinding layout_bindings[16];
    for (size_t i = 0; i < binding_count; ++i) {
        if ((types[i] != VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER && types[i] != VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER &&
                types[i] != VK_DESCRIPTOR_TYPE_STORAGE_BUFFER) ||
            (stages[i] & (VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT | VK_SHADER_STAGE_COMPUTE_BIT)) == 0) {
            strncpy(result->error, "Unsupported bind group layout entry", sizeof(result->error) - 1); return (size_t)result;
        }
        for (size_t previous = 0; previous < i; ++previous) if (bindings[previous] == bindings[i]) {
            strncpy(result->error, "Duplicate bind group binding", sizeof(result->error) - 1); return (size_t)result;
        }
        result->bindings[i] = bindings[i]; result->types[i] = types[i]; result->stages[i] = stages[i];
        layout_bindings[i] = (VkDescriptorSetLayoutBinding){bindings[i], types[i], 1, stages[i], NULL};
    }
    result->binding_count = (uint32_t)binding_count;
    VkDescriptorSetLayoutCreateInfo info = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, NULL, 0,
        (uint32_t)binding_count, layout_bindings};
    if (create_layout(device->device, &info, NULL, &result->layout) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create Vulkan bind group layout", sizeof(result->error) - 1); return (size_t)result;
    }
    result->available = true; return (size_t)result;
}

size_t graphene_vk_bind_group_layout_create(size_t device_handle, uint32_t binding, uint32_t stage) {
    uint32_t type = VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER;
    return graphene_vk_bind_group_layout_create_entries(device_handle, &binding, 1, 1, &type, 1, 1, &stage, 1, 1);
}

bool graphene_vk_bind_group_layout_available(size_t handle) { GrapheneVkBindGroupLayout *l = (GrapheneVkBindGroupLayout *)handle; return l != NULL && l->available; }
encore_str graphene_vk_bind_group_layout_error(size_t handle) { GrapheneVkBindGroupLayout *l = (GrapheneVkBindGroupLayout *)handle; return graphene_string(l == NULL ? "Invalid bind group layout" : l->error); }
bool graphene_vk_bind_group_layout_destroy(size_t handle) {
    GrapheneVkBindGroupLayout *layout = (GrapheneVkBindGroupLayout *)handle;
    if (layout == NULL) return false;
    if (layout->layout != NULL && layout->owner != NULL && layout->owner->device != NULL && layout->destroy_layout != NULL)
        layout->destroy_layout(layout->owner->device, layout->layout, NULL);
    free(layout); return true;
}

size_t graphene_vk_bind_group_create(size_t device_handle, size_t layout_handle, size_t buffer_handle,
    uint64_t offset, uint64_t range) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkBindGroupLayout *layout = (GrapheneVkBindGroupLayout *)layout_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    GrapheneVkBindGroup *result = (GrapheneVkBindGroup *)calloc(1, sizeof(GrapheneVkBindGroup));
    if (result == NULL) return 0;
    result->owner = device; result->layout = layout;
    if (device == NULL || !device->available || layout == NULL || !layout->available || layout->owner != device ||
        buffer == NULL || !buffer->available || buffer->owner != device || range == 0 || offset > buffer->size || range > buffer->size - offset) {
        strncpy(result->error, "Invalid uniform bind group resources", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateDescriptorPool create_pool = (PFN_vkCreateDescriptorPool)device->get_device_proc(device->device, "vkCreateDescriptorPool");
    result->destroy_pool = (PFN_vkDestroyDescriptorPool)device->get_device_proc(device->device, "vkDestroyDescriptorPool");
    PFN_vkAllocateDescriptorSets allocate_sets = (PFN_vkAllocateDescriptorSets)device->get_device_proc(device->device, "vkAllocateDescriptorSets");
    PFN_vkUpdateDescriptorSets update_sets = (PFN_vkUpdateDescriptorSets)device->get_device_proc(device->device, "vkUpdateDescriptorSets");
    if (create_pool == NULL || result->destroy_pool == NULL || allocate_sets == NULL || update_sets == NULL) {
        strncpy(result->error, "Vulkan descriptor set functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorPoolSize pool_size = {VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1};
    VkDescriptorPoolCreateInfo pool_info = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, 1, 1, &pool_size};
    if (create_pool(device->device, &pool_info, NULL, &result->pool) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create Vulkan descriptor pool", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorSetAllocateInfo allocate = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, result->pool, 1, &layout->layout};
    if (allocate_sets(device->device, &allocate, &result->set) != VK_SUCCESS) {
        strncpy(result->error, "Unable to allocate Vulkan descriptor set", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorBufferInfo buffer_info = {buffer->buffer, offset, range};
    if (layout->binding_count != 1 || layout->types[0] != VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER) {
        strncpy(result->error, "Uniform bind group requires one uniform layout entry", sizeof(result->error) - 1); return (size_t)result;
    }
    VkWriteDescriptorSet write = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, result->set, layout->bindings[0],
        0, 1, VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, NULL, &buffer_info, NULL};
    update_sets(device->device, 1, &write, 0, NULL);
    result->available = true; return (size_t)result;
}

size_t graphene_vk_storage_bind_group_create(size_t device_handle, size_t layout_handle, size_t buffer_handle,
    uint64_t offset, uint64_t range) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkBindGroupLayout *layout = (GrapheneVkBindGroupLayout *)layout_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    GrapheneVkBindGroup *result = (GrapheneVkBindGroup *)calloc(1, sizeof(GrapheneVkBindGroup));
    if (result == NULL) return 0;
    result->owner = device; result->layout = layout;
    if (device == NULL || !device->available || layout == NULL || !layout->available || layout->owner != device ||
        layout->binding_count != 1 || layout->types[0] != VK_DESCRIPTOR_TYPE_STORAGE_BUFFER ||
        buffer == NULL || !buffer->available || buffer->owner != device || range == 0 || offset > buffer->size || range > buffer->size - offset) {
        strncpy(result->error, "Invalid storage bind group resources", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateDescriptorPool create_pool = (PFN_vkCreateDescriptorPool)device->get_device_proc(device->device, "vkCreateDescriptorPool");
    result->destroy_pool = (PFN_vkDestroyDescriptorPool)device->get_device_proc(device->device, "vkDestroyDescriptorPool");
    PFN_vkAllocateDescriptorSets allocate_sets = (PFN_vkAllocateDescriptorSets)device->get_device_proc(device->device, "vkAllocateDescriptorSets");
    PFN_vkUpdateDescriptorSets update_sets = (PFN_vkUpdateDescriptorSets)device->get_device_proc(device->device, "vkUpdateDescriptorSets");
    if (create_pool == NULL || result->destroy_pool == NULL || allocate_sets == NULL || update_sets == NULL) {
        strncpy(result->error, "Vulkan storage descriptor functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorPoolSize pool_size = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
    VkDescriptorPoolCreateInfo pool_info = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, 1, 1, &pool_size};
    if (create_pool(device->device, &pool_info, NULL, &result->pool) != VK_SUCCESS) return (size_t)result;
    VkDescriptorSetAllocateInfo allocate = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, result->pool, 1, &layout->layout};
    if (allocate_sets(device->device, &allocate, &result->set) != VK_SUCCESS) return (size_t)result;
    VkDescriptorBufferInfo buffer_info = {buffer->buffer, offset, range};
    VkWriteDescriptorSet write = {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, result->set, layout->bindings[0],
        0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &buffer_info, NULL};
    update_sets(device->device, 1, &write, 0, NULL);
    result->available = true; return (size_t)result;
}

size_t graphene_vk_compute_pipeline_create(size_t device_handle, size_t shader_handle, size_t layout_handle) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkShader *shader = (GrapheneVkShader *)shader_handle;
    GrapheneVkBindGroupLayout *bind_layout = (GrapheneVkBindGroupLayout *)layout_handle;
    GrapheneVkComputePipeline *result = (GrapheneVkComputePipeline *)calloc(1, sizeof(GrapheneVkComputePipeline));
    if (result == NULL) return 0;
    result->owner = device;
    if (device == NULL || !device->available || shader == NULL || !shader->available || shader->owner != device ||
        shader->stage != VK_SHADER_STAGE_COMPUTE_BIT || bind_layout == NULL || !bind_layout->available || bind_layout->owner != device) {
        strncpy(result->error, "Invalid compute pipeline resources", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreatePipelineLayout create_layout = (PFN_vkCreatePipelineLayout)device->get_device_proc(device->device, "vkCreatePipelineLayout");
    PFN_vkCreateComputePipelines create_pipeline = (PFN_vkCreateComputePipelines)device->get_device_proc(device->device, "vkCreateComputePipelines");
    result->destroy_pipeline_layout = (PFN_vkDestroyPipelineLayout)device->get_device_proc(device->device, "vkDestroyPipelineLayout");
    result->destroy_pipeline = (PFN_vkDestroyPipeline)device->get_device_proc(device->device, "vkDestroyPipeline");
    if (create_layout == NULL || create_pipeline == NULL || result->destroy_pipeline_layout == NULL || result->destroy_pipeline == NULL) {
        strncpy(result->error, "Vulkan compute pipeline functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkPipelineLayoutCreateInfo layout_info = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0, 1, &bind_layout->layout, 0, NULL};
    if (create_layout(device->device, &layout_info, NULL, &result->layout) != VK_SUCCESS) return (size_t)result;
    VkComputePipelineCreateInfo info = {VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, NULL, 0,
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_COMPUTE_BIT, shader->module, "main", NULL},
        result->layout, NULL, -1};
    if (create_pipeline(device->device, NULL, 1, &info, NULL, &result->pipeline) != VK_SUCCESS) return (size_t)result;
    result->available = true; return (size_t)result;
}

bool graphene_vk_compute_pipeline_available(size_t handle) { GrapheneVkComputePipeline *p = (GrapheneVkComputePipeline *)handle; return p != NULL && p->available; }
encore_str graphene_vk_compute_pipeline_error(size_t handle) { GrapheneVkComputePipeline *p = (GrapheneVkComputePipeline *)handle; return graphene_string(p == NULL ? "Invalid compute pipeline" : p->error); }
bool graphene_vk_compute_pipeline_destroy(size_t handle) {
    GrapheneVkComputePipeline *pipeline = (GrapheneVkComputePipeline *)handle;
    if (pipeline == NULL) return false;
    if (pipeline->owner != NULL && pipeline->owner->device != NULL) {
        if (pipeline->pipeline != NULL && pipeline->destroy_pipeline != NULL) pipeline->destroy_pipeline(pipeline->owner->device, pipeline->pipeline, NULL);
        if (pipeline->layout != NULL && pipeline->destroy_pipeline_layout != NULL) pipeline->destroy_pipeline_layout(pipeline->owner->device, pipeline->layout, NULL);
    }
    free(pipeline); return true;
}

bool graphene_vk_bind_group_available(size_t handle) { GrapheneVkBindGroup *g = (GrapheneVkBindGroup *)handle; return g != NULL && g->available; }
encore_str graphene_vk_bind_group_error(size_t handle) { GrapheneVkBindGroup *g = (GrapheneVkBindGroup *)handle; return graphene_string(g == NULL ? "Invalid bind group" : g->error); }
bool graphene_vk_bind_group_destroy(size_t handle) {
    GrapheneVkBindGroup *group = (GrapheneVkBindGroup *)handle;
    if (group == NULL) return false;
    if (group->pool != NULL && group->owner != NULL && group->owner->device != NULL && group->destroy_pool != NULL)
        group->destroy_pool(group->owner->device, group->pool, NULL);
    free(group); return true;
}

size_t graphene_vk_sampler_create(size_t device_handle) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkSampler *result = (GrapheneVkSampler *)calloc(1, sizeof(GrapheneVkSampler));
    if (result == NULL) return 0;
    result->owner = device;
    if (device == NULL || !device->available) {
        strncpy(result->error, "Invalid sampler device", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateSampler create_sampler = (PFN_vkCreateSampler)device->get_device_proc(device->device, "vkCreateSampler");
    result->destroy_sampler = (PFN_vkDestroySampler)device->get_device_proc(device->device, "vkDestroySampler");
    if (create_sampler == NULL || result->destroy_sampler == NULL) {
        strncpy(result->error, "Vulkan sampler functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkSamplerCreateInfo info = {VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, NULL, 0, VK_FILTER_LINEAR, VK_FILTER_LINEAR,
        VK_SAMPLER_MIPMAP_MODE_LINEAR, VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, 0.0f, 0, 1.0f, 0, 0, 0.0f, 16.0f, 0, 0};
    if (create_sampler(device->device, &info, NULL, &result->sampler) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create Vulkan sampler", sizeof(result->error) - 1); return (size_t)result;
    }
    result->available = true; return (size_t)result;
}

bool graphene_vk_sampler_available(size_t handle) { GrapheneVkSampler *s = (GrapheneVkSampler *)handle; return s != NULL && s->available; }
encore_str graphene_vk_sampler_error(size_t handle) { GrapheneVkSampler *s = (GrapheneVkSampler *)handle; return graphene_string(s == NULL ? "Invalid sampler" : s->error); }
bool graphene_vk_sampler_destroy(size_t handle) {
    GrapheneVkSampler *sampler = (GrapheneVkSampler *)handle;
    if (sampler == NULL) return false;
    if (sampler->sampler != NULL && sampler->owner != NULL && sampler->owner->device != NULL && sampler->destroy_sampler != NULL)
        sampler->destroy_sampler(sampler->owner->device, sampler->sampler, NULL);
    free(sampler); return true;
}

size_t graphene_vk_material_bind_group_create(size_t device_handle, size_t layout_handle,
    uint32_t uniform_binding, size_t buffer_handle, uint64_t offset, uint64_t range,
    uint32_t texture_binding, size_t texture_handle, size_t sampler_handle) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkBindGroupLayout *layout = (GrapheneVkBindGroupLayout *)layout_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    GrapheneVkTexture *texture = (GrapheneVkTexture *)texture_handle;
    GrapheneVkSampler *sampler = (GrapheneVkSampler *)sampler_handle;
    GrapheneVkBindGroup *result = (GrapheneVkBindGroup *)calloc(1, sizeof(GrapheneVkBindGroup));
    if (result == NULL) return 0;
    result->owner = device; result->layout = layout;
    bool uniform_found = false, texture_found = false;
    if (layout != NULL) for (uint32_t i = 0; i < layout->binding_count; ++i) {
        if (layout->bindings[i] == uniform_binding && layout->types[i] == VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER) uniform_found = true;
        if (layout->bindings[i] == texture_binding && layout->types[i] == VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER) texture_found = true;
    }
    if (device == NULL || !device->available || layout == NULL || !layout->available || layout->owner != device ||
        layout->binding_count != 2 || !uniform_found || !texture_found || buffer == NULL || !buffer->available || buffer->owner != device ||
        texture == NULL || !texture->available || texture->owner != device || texture->layout != VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL ||
        sampler == NULL || !sampler->available || sampler->owner != device || range == 0 || offset > buffer->size || range > buffer->size - offset) {
        strncpy(result->error, "Invalid material bind group resources", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateDescriptorPool create_pool = (PFN_vkCreateDescriptorPool)device->get_device_proc(device->device, "vkCreateDescriptorPool");
    result->destroy_pool = (PFN_vkDestroyDescriptorPool)device->get_device_proc(device->device, "vkDestroyDescriptorPool");
    PFN_vkAllocateDescriptorSets allocate_sets = (PFN_vkAllocateDescriptorSets)device->get_device_proc(device->device, "vkAllocateDescriptorSets");
    PFN_vkUpdateDescriptorSets update_sets = (PFN_vkUpdateDescriptorSets)device->get_device_proc(device->device, "vkUpdateDescriptorSets");
    if (create_pool == NULL || result->destroy_pool == NULL || allocate_sets == NULL || update_sets == NULL) {
        strncpy(result->error, "Vulkan material descriptor functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorPoolSize pool_sizes[2] = {{VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, 1}, {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1}};
    VkDescriptorPoolCreateInfo pool_info = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, 1, 2, pool_sizes};
    if (create_pool(device->device, &pool_info, NULL, &result->pool) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create material descriptor pool", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorSetAllocateInfo allocate = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, result->pool, 1, &layout->layout};
    if (allocate_sets(device->device, &allocate, &result->set) != VK_SUCCESS) {
        strncpy(result->error, "Unable to allocate material descriptor set", sizeof(result->error) - 1); return (size_t)result;
    }
    VkDescriptorBufferInfo buffer_info = {buffer->buffer, offset, range};
    VkDescriptorImageInfo image_info = {sampler->sampler, texture->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
    VkWriteDescriptorSet writes[2] = {
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, result->set, uniform_binding, 0, 1,
            VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER, NULL, &buffer_info, NULL},
        {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, result->set, texture_binding, 0, 1,
            VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &image_info, NULL, NULL}
    };
    update_sets(device->device, 2, writes, 0, NULL);
    result->available = true; return (size_t)result;
}

size_t graphene_vk_pipeline_create(size_t device_handle, size_t swapchain_handle, size_t vertex_handle, size_t fragment_handle,
    size_t bind_group_layout_handle, bool depth_test, uint32_t cull_mode, bool alpha_blend,
    uint32_t vertex_stride, const uint32_t *locations, size_t location_count, size_t location_capacity,
    const uint32_t *formats, size_t format_count, size_t format_capacity,
    const uint32_t *offsets, size_t offset_count, size_t offset_capacity) {
    (void)location_capacity; (void)format_capacity; (void)offset_capacity;
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkSwapchain *swapchain = (GrapheneVkSwapchain *)swapchain_handle;
    GrapheneVkShader *vertex = (GrapheneVkShader *)vertex_handle;
    GrapheneVkShader *fragment = (GrapheneVkShader *)fragment_handle;
    GrapheneVkBindGroupLayout *bind_group_layout = (GrapheneVkBindGroupLayout *)bind_group_layout_handle;
    GrapheneVkPipeline *result = (GrapheneVkPipeline *)calloc(1, sizeof(GrapheneVkPipeline));
    if (result == NULL) return 0;
    result->owner = device;
    result->depth_test = depth_test;
    if (device == NULL || !device->available || swapchain == NULL || !swapchain->available ||
        swapchain->owner != device || vertex == NULL || fragment == NULL || !vertex->available || !fragment->available ||
        vertex->owner != device || fragment->owner != device || vertex->stage != VK_SHADER_STAGE_VERTEX_BIT ||
        fragment->stage != VK_SHADER_STAGE_FRAGMENT_BIT ||
        (bind_group_layout != NULL && (!bind_group_layout->available || bind_group_layout->owner != device)) ||
        location_count != format_count ||
        location_count != offset_count || location_count > 16 || (location_count > 0 && vertex_stride == 0) ||
        (cull_mode != VK_CULL_MODE_NONE && cull_mode != VK_CULL_MODE_FRONT_BIT && cull_mode != VK_CULL_MODE_BACK_BIT)) {
        strncpy(result->error, "Invalid render pipeline resources", sizeof(result->error) - 1); return (size_t)result;
    }
    PFN_vkCreateRenderPass create_render_pass = (PFN_vkCreateRenderPass)device->get_device_proc(device->device, "vkCreateRenderPass");
    PFN_vkCreatePipelineLayout create_layout = (PFN_vkCreatePipelineLayout)device->get_device_proc(device->device, "vkCreatePipelineLayout");
    PFN_vkCreateGraphicsPipelines create_pipeline = (PFN_vkCreateGraphicsPipelines)device->get_device_proc(device->device, "vkCreateGraphicsPipelines");
    result->destroy_render_pass = (PFN_vkDestroyRenderPass)device->get_device_proc(device->device, "vkDestroyRenderPass");
    result->destroy_pipeline_layout = (PFN_vkDestroyPipelineLayout)device->get_device_proc(device->device, "vkDestroyPipelineLayout");
    result->destroy_pipeline = (PFN_vkDestroyPipeline)device->get_device_proc(device->device, "vkDestroyPipeline");
    if (create_render_pass == NULL || create_layout == NULL || create_pipeline == NULL ||
        result->destroy_render_pass == NULL || result->destroy_pipeline_layout == NULL || result->destroy_pipeline == NULL) {
        strncpy(result->error, "Required Vulkan pipeline functions were not found", sizeof(result->error) - 1); return (size_t)result;
    }
    VkAttachmentDescription attachments[2] = {
        {0, swapchain->format, VK_SAMPLE_COUNT_1_BIT, VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_STORE,
            VK_ATTACHMENT_LOAD_OP_DONT_CARE, VK_ATTACHMENT_STORE_OP_DONT_CARE,
            VK_IMAGE_LAYOUT_UNDEFINED,
            swapchain->offscreen ? VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL : VK_IMAGE_LAYOUT_PRESENT_SRC_KHR},
        {0, 126, VK_SAMPLE_COUNT_1_BIT, VK_ATTACHMENT_LOAD_OP_CLEAR, VK_ATTACHMENT_STORE_OP_DONT_CARE,
            VK_ATTACHMENT_LOAD_OP_DONT_CARE, VK_ATTACHMENT_STORE_OP_DONT_CARE,
            VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL}
    };
    VkAttachmentReference color_reference = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkAttachmentReference depth_reference = {1, VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL};
    VkSubpassDescription subpass = {0, VK_PIPELINE_BIND_POINT_GRAPHICS, 0, NULL, 1, &color_reference, NULL,
        depth_test ? &depth_reference : NULL, 0, NULL};
    VkSubpassDependency dependency = {VK_SUBPASS_EXTERNAL, 0,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT,
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT | VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT,
        0, VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT | VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT, 0};
    VkRenderPassCreateInfo render_pass_info = {VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, NULL, 0,
        depth_test ? 2 : 1, attachments, 1, &subpass, 1, &dependency};
    if (create_render_pass(device->device, &render_pass_info, NULL, &result->render_pass) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create render pipeline pass", sizeof(result->error) - 1); return (size_t)result;
    }
    void *descriptor_layout = bind_group_layout == NULL ? NULL : bind_group_layout->layout;
    VkPipelineLayoutCreateInfo layout_info = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0,
        bind_group_layout == NULL ? 0 : 1, bind_group_layout == NULL ? NULL : &descriptor_layout, 0, NULL};
    if (create_layout(device->device, &layout_info, NULL, &result->layout) != VK_SUCCESS) {
        strncpy(result->error, "Unable to create render pipeline layout", sizeof(result->error) - 1); return (size_t)result;
    }
    VkPipelineShaderStageCreateInfo stages[2] = {
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, vertex->module, "main", NULL},
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, fragment->module, "main", NULL}
    };
    VkVertexInputBindingDescription binding = {0, vertex_stride, 0};
    VkVertexInputAttributeDescription attributes[16];
    for (size_t i = 0; i < location_count; ++i) {
        attributes[i].location = locations[i]; attributes[i].binding = 0;
        attributes[i].format = formats[i]; attributes[i].offset = offsets[i];
    }
    VkPipelineVertexInputStateCreateInfo vertex_input = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO, NULL, 0,
        location_count == 0 ? 0 : 1, location_count == 0 ? NULL : &binding,
        (uint32_t)location_count, location_count == 0 ? NULL : attributes};
    VkPipelineInputAssemblyStateCreateInfo assembly = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, NULL, 0, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST, 0};
    VkPipelineViewportStateCreateInfo viewport = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, NULL, 0, 1, NULL, 1, NULL};
    VkPipelineRasterizationStateCreateInfo raster = {VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, NULL, 0,
        0, 0, VK_POLYGON_MODE_FILL, cull_mode, VK_FRONT_FACE_CLOCKWISE, 0, 0.0f, 0.0f, 0.0f, 1.0f};
    VkPipelineMultisampleStateCreateInfo multisample = {VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, NULL, 0,
        VK_SAMPLE_COUNT_1_BIT, 0, 0.0f, NULL, 0, 0};
    VkPipelineDepthStencilStateCreateInfo depth = {VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO, NULL, 0,
        1, 1, VK_COMPARE_OP_LESS, 0, 0, {0}, {0}, 0.0f, 1.0f};
    VkPipelineColorBlendAttachmentState blend_attachment = {alpha_blend ? 1u : 0u,
        alpha_blend ? VK_BLEND_FACTOR_SRC_ALPHA : VK_BLEND_FACTOR_ONE,
        alpha_blend ? VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA : VK_BLEND_FACTOR_ZERO, VK_BLEND_OP_ADD,
        VK_BLEND_FACTOR_ONE, alpha_blend ? VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA : VK_BLEND_FACTOR_ZERO,
        VK_BLEND_OP_ADD, VK_COLOR_COMPONENT_RGBA_BITS};
    VkPipelineColorBlendStateCreateInfo blend = {VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, NULL, 0,
        0, 0, 1, &blend_attachment, {0.0f, 0.0f, 0.0f, 0.0f}};
    uint32_t dynamic_states[2] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamic = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, NULL, 0, 2, dynamic_states};
    VkGraphicsPipelineCreateInfo pipeline_info = {VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, NULL, 0,
        2, stages, &vertex_input, &assembly, NULL, &viewport, &raster, &multisample, depth_test ? &depth : NULL, &blend, &dynamic,
        result->layout, result->render_pass, 0, NULL, -1};
    VkResult status = create_pipeline(device->device, NULL, 1, &pipeline_info, NULL, &result->pipeline);
    if (status != VK_SUCCESS) {
        snprintf(result->error, sizeof(result->error), "Unable to create Vulkan render pipeline (result %d)", status);
        return (size_t)result;
    }
    result->format = swapchain->format;
    result->available = true;
    return (size_t)result;
}

bool graphene_vk_pipeline_available(size_t handle) { GrapheneVkPipeline *p = (GrapheneVkPipeline *)handle; return p != NULL && p->available; }
encore_str graphene_vk_pipeline_error(size_t handle) { GrapheneVkPipeline *p = (GrapheneVkPipeline *)handle; return graphene_string(p == NULL ? "Invalid render pipeline" : p->error); }
bool graphene_vk_pipeline_destroy(size_t handle) {
    GrapheneVkPipeline *pipeline = (GrapheneVkPipeline *)handle;
    if (pipeline == NULL) return false;
    if (pipeline->owner != NULL && pipeline->owner->device != NULL) {
        if (pipeline->pipeline != NULL && pipeline->destroy_pipeline != NULL) pipeline->destroy_pipeline(pipeline->owner->device, pipeline->pipeline, NULL);
        if (pipeline->layout != NULL && pipeline->destroy_pipeline_layout != NULL) pipeline->destroy_pipeline_layout(pipeline->owner->device, pipeline->layout, NULL);
        if (pipeline->render_pass != NULL && pipeline->destroy_render_pass != NULL) pipeline->destroy_render_pass(pipeline->owner->device, pipeline->render_pass, NULL);
    }
    free(pipeline); return true;
}
