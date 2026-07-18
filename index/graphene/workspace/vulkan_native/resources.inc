/* Command submissions, buffers, textures and transfer operations. */
size_t graphene_vk_encoder_create(size_t device_handle) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)calloc(1, sizeof(GrapheneVkEncoder));
    if (encoder == NULL) return 0;
    encoder->owner = device;
    if (device == NULL || !device->available || device->command_pool == NULL) {
        strncpy(encoder->error, "Invalid Graphene graphics device", sizeof(encoder->error) - 1); return (size_t)encoder;
    }
    VkCommandBufferAllocateInfo allocate_info = {
        VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, device->command_pool,
        VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1
    };
    if (device->allocate_command_buffers(device->device, &allocate_info, &encoder->command_buffer) != VK_SUCCESS) {
        strncpy(encoder->error, "Unable to allocate Vulkan command buffer", sizeof(encoder->error) - 1); return (size_t)encoder;
    }
    VkCommandBufferBeginInfo begin_info = {
        VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL, VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL
    };
    if (device->begin_command_buffer(encoder->command_buffer, &begin_info) != VK_SUCCESS) {
        strncpy(encoder->error, "Unable to begin Vulkan command buffer", sizeof(encoder->error) - 1); return (size_t)encoder;
    }
    encoder->recording = true;
    return (size_t)encoder;
}

bool graphene_vk_encoder_available(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    return encoder != NULL && encoder->recording && encoder->command_buffer != NULL;
}

encore_str graphene_vk_encoder_error(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    return graphene_string(encoder == NULL ? "Invalid command encoder" : encoder->error);
}

bool graphene_vk_encoder_bind_compute_pipeline(size_t encoder_handle, size_t pipeline_handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)encoder_handle;
    GrapheneVkComputePipeline *pipeline = (GrapheneVkComputePipeline *)pipeline_handle;
    if (encoder == NULL || !encoder->recording || pipeline == NULL || !pipeline->available || pipeline->owner != encoder->owner) return false;
    encoder->owner->cmd_bind_pipeline(encoder->command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline->pipeline);
    return true;
}

bool graphene_vk_encoder_bind_compute_group(size_t encoder_handle, size_t pipeline_handle, size_t group_handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)encoder_handle;
    GrapheneVkComputePipeline *pipeline = (GrapheneVkComputePipeline *)pipeline_handle;
    GrapheneVkBindGroup *group = (GrapheneVkBindGroup *)group_handle;
    if (encoder == NULL || !encoder->recording || pipeline == NULL || !pipeline->available || pipeline->owner != encoder->owner ||
        group == NULL || !group->available || group->owner != encoder->owner) return false;
    encoder->owner->cmd_bind_descriptor_sets(encoder->command_buffer, VK_PIPELINE_BIND_POINT_COMPUTE,
        pipeline->layout, 0, 1, &group->set, 0, NULL);
    return true;
}

bool graphene_vk_encoder_dispatch(size_t handle, uint32_t x, uint32_t y, uint32_t z) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    if (encoder == NULL || !encoder->recording || x == 0 || y == 0 || z == 0) return false;
    encoder->owner->cmd_dispatch(encoder->command_buffer, x, y, z); return true;
}

bool graphene_vk_encoder_storage_host_barrier(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    if (encoder == NULL || !encoder->recording) return false;
    VkMemoryBarrier barrier = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, NULL, VK_ACCESS_SHADER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT};
    encoder->owner->cmd_pipeline_barrier(encoder->command_buffer, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
        VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    return true;
}

bool graphene_vk_encoder_transfer_host_barrier(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    if (encoder == NULL || !encoder->recording) return false;
    VkMemoryBarrier barrier = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, NULL, VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_HOST_READ_BIT};
    encoder->owner->cmd_pipeline_barrier(encoder->command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    return true;
}

bool graphene_vk_encoder_transfer_geometry_barrier(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    if (encoder == NULL || !encoder->recording) return false;
    VkMemoryBarrier barrier = {VK_STRUCTURE_TYPE_MEMORY_BARRIER, NULL, VK_ACCESS_TRANSFER_WRITE_BIT,
        VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT | VK_ACCESS_INDEX_READ_BIT};
    encoder->owner->cmd_pipeline_barrier(encoder->command_buffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_VERTEX_INPUT_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    return true;
}

bool graphene_vk_encoder_copy_buffer(size_t encoder_handle, size_t source_handle, size_t destination_handle,
    uint64_t source_offset, uint64_t destination_offset, uint64_t size) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)encoder_handle;
    GrapheneVkBuffer *source = (GrapheneVkBuffer *)source_handle;
    GrapheneVkBuffer *destination = (GrapheneVkBuffer *)destination_handle;
    if (encoder == NULL || !encoder->recording || source == NULL || destination == NULL ||
        !source->available || !destination->available || source->owner != encoder->owner || destination->owner != encoder->owner ||
        (source->usage & 1u) == 0 || (destination->usage & 2u) == 0 || size == 0 ||
        source_offset > source->size || size > source->size - source_offset ||
        destination_offset > destination->size || size > destination->size - destination_offset) return false;
    VkBufferCopy region = {source_offset, destination_offset, size};
    encoder->owner->cmd_copy_buffer(encoder->command_buffer, source->buffer, destination->buffer, 1, &region);
    return true;
}

size_t graphene_vk_encoder_submit(size_t handle);
bool graphene_vk_submission_wait(size_t handle, uint64_t timeout_ns);
bool graphene_vk_submission_destroy(size_t handle);

bool graphene_vk_encoder_submit_wait(size_t handle) {
    size_t submission = graphene_vk_encoder_submit(handle);
    if (submission == 0) return false;
    bool complete = graphene_vk_submission_wait(submission, UINT64_MAX);
    graphene_vk_submission_destroy(submission);
    return complete;
}

size_t graphene_vk_encoder_submit(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)calloc(1, sizeof(GrapheneVkSubmission));
    if (submission == NULL) return 0;
    if (encoder == NULL || !encoder->recording || encoder->submitted || encoder->owner == NULL) {
        strncpy(submission->error, "Invalid command encoder state", sizeof(submission->error) - 1); return (size_t)submission;
    }
    GrapheneVkDevice *device = encoder->owner;
    submission->owner = device;
    if (device->end_command_buffer(encoder->command_buffer) != VK_SUCCESS) {
        strncpy(submission->error, "Unable to end Vulkan command buffer", sizeof(submission->error) - 1); return (size_t)submission;
    }
    encoder->recording = false;
    VkFenceCreateInfo fence_info = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL, 0};
    if (device->create_fence(device->device, &fence_info, NULL, &submission->fence) != VK_SUCCESS) {
        strncpy(submission->error, "Unable to create Vulkan submission fence", sizeof(submission->error) - 1); return (size_t)submission;
    }
    void *buffers[1] = {encoder->command_buffer};
    VkSubmitInfo submit = {VK_STRUCTURE_TYPE_SUBMIT_INFO, NULL, 0, NULL, NULL, 1, buffers, 0, NULL};
    if (device->queue_submit(device->queue, 1, &submit, submission->fence) != VK_SUCCESS) {
        strncpy(submission->error, "Unable to submit Vulkan command buffer", sizeof(submission->error) - 1); return (size_t)submission;
    }
    submission->command_buffer = encoder->command_buffer;
    encoder->command_buffer = NULL;
    encoder->submitted = true;
    return (size_t)submission;
}

bool graphene_vk_submission_complete(size_t handle) {
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)handle;
    if (submission == NULL || submission->owner == NULL || submission->fence == NULL) return false;
    if (submission->complete) return true;
    VkResult status = submission->owner->get_fence_status(submission->owner->device, submission->fence);
    if (status == VK_SUCCESS) submission->complete = true;
    return submission->complete;
}

bool graphene_vk_submission_available(size_t handle) {
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)handle;
    return submission != NULL && submission->owner != NULL && submission->fence != NULL && submission->command_buffer != NULL;
}

bool graphene_vk_submission_wait(size_t handle, uint64_t timeout_ns) {
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)handle;
    if (submission == NULL || submission->owner == NULL || submission->fence == NULL) return false;
    if (submission->complete) return true;
    void *fences[1] = {submission->fence};
    VkResult status = submission->owner->wait_for_fences(submission->owner->device, 1, fences, 1, timeout_ns);
    if (status == VK_SUCCESS) submission->complete = true;
    return submission->complete;
}

encore_str graphene_vk_submission_error(size_t handle) {
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)handle;
    return graphene_string(submission == NULL ? "Invalid GPU submission" : submission->error);
}

bool graphene_vk_submission_destroy(size_t handle) {
    GrapheneVkSubmission *submission = (GrapheneVkSubmission *)handle;
    if (submission == NULL) return false;
    if (submission->owner != NULL && submission->owner->device != NULL) {
        if (submission->fence != NULL && !submission->complete) {
            void *fences[1] = {submission->fence};
            submission->owner->wait_for_fences(submission->owner->device, 1, fences, 1, UINT64_MAX);
        }
        if (submission->command_buffer != NULL)
            submission->owner->free_command_buffers(submission->owner->device, submission->owner->command_pool, 1, &submission->command_buffer);
        if (submission->fence != NULL)
            submission->owner->destroy_fence(submission->owner->device, submission->fence, NULL);
    }
    free(submission);
    return true;
}

bool graphene_vk_encoder_destroy(size_t handle) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)handle;
    if (encoder == NULL) return false;
    if (encoder->owner != NULL && encoder->command_buffer != NULL && encoder->owner->device != NULL)
        encoder->owner->free_command_buffers(encoder->owner->device, encoder->owner->command_pool, 1, &encoder->command_buffer);
    free(encoder);
    return true;
}

static uint32_t graphene_memory_type(GrapheneVkDevice *device, uint32_t allowed, uint32_t required) {
    for (uint32_t i = 0; i < device->memory_properties.memoryTypeCount; ++i) {
        if ((allowed & (1u << i)) != 0 &&
            (device->memory_properties.memoryTypes[i].propertyFlags & required) == required) return i;
    }
    return UINT32_MAX;
}

size_t graphene_vk_buffer_create(size_t device_handle, uint64_t size, uint32_t usage, bool host_visible) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)calloc(1, sizeof(GrapheneVkBuffer));
    if (buffer == NULL) return 0;
    buffer->owner = device;
    buffer->size = size;
    buffer->usage = usage;
    buffer->host_visible = host_visible;
    if (device == NULL || !device->available || size == 0 || usage == 0) {
        strncpy(buffer->error, "Invalid GPU buffer description", sizeof(buffer->error) - 1); return (size_t)buffer;
    }
    VkBufferCreateInfo create_info = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, size, usage, 0, 0, NULL};
    if (device->create_buffer(device->device, &create_info, NULL, &buffer->buffer) != VK_SUCCESS) {
        strncpy(buffer->error, "Unable to create Vulkan buffer", sizeof(buffer->error) - 1); return (size_t)buffer;
    }
    VkMemoryRequirements requirements;
    device->get_buffer_requirements(device->device, buffer->buffer, &requirements);
    uint32_t properties = host_visible
        ? VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT
        : VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT;
    uint32_t memory_type = graphene_memory_type(device, requirements.memoryTypeBits, properties);
    if (memory_type == UINT32_MAX && !host_visible)
        memory_type = graphene_memory_type(device, requirements.memoryTypeBits, 0);
    if (memory_type == UINT32_MAX) {
        strncpy(buffer->error, "No compatible Vulkan memory type", sizeof(buffer->error) - 1); return (size_t)buffer;
    }
    VkMemoryAllocateInfo allocate_info = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, requirements.size, memory_type};
    if (device->allocate_memory(device->device, &allocate_info, NULL, &buffer->memory) != VK_SUCCESS) {
        strncpy(buffer->error, "Unable to allocate Vulkan buffer memory", sizeof(buffer->error) - 1); return (size_t)buffer;
    }
    if (device->bind_buffer_memory(device->device, buffer->buffer, buffer->memory, 0) != VK_SUCCESS) {
        strncpy(buffer->error, "Unable to bind Vulkan buffer memory", sizeof(buffer->error) - 1); return (size_t)buffer;
    }
    buffer->available = true;
    return (size_t)buffer;
}

bool graphene_vk_buffer_available(size_t handle) { GrapheneVkBuffer *b = (GrapheneVkBuffer *)handle; return b != NULL && b->available; }
encore_str graphene_vk_buffer_error(size_t handle) { GrapheneVkBuffer *b = (GrapheneVkBuffer *)handle; return graphene_string(b == NULL ? "Invalid GPU buffer" : b->error); }
uint64_t graphene_vk_buffer_size(size_t handle) { GrapheneVkBuffer *b = (GrapheneVkBuffer *)handle; return b == NULL ? 0 : b->size; }
bool graphene_vk_buffer_host_visible(size_t handle) { GrapheneVkBuffer *b = (GrapheneVkBuffer *)handle; return b != NULL && b->host_visible; }

bool graphene_vk_buffer_write_u32(size_t handle, uint64_t offset, uint32_t value) {
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)handle;
    if (buffer == NULL || !buffer->available || !buffer->host_visible || offset > buffer->size || buffer->size - offset < 4) return false;
    void *mapped = NULL;
    if (buffer->owner->map_memory(buffer->owner->device, buffer->memory, offset, 4, 0, &mapped) != VK_SUCCESS || mapped == NULL) return false;
    memcpy(mapped, &value, sizeof(value));
    buffer->owner->unmap_memory(buffer->owner->device, buffer->memory);
    return true;
}

bool graphene_vk_buffer_write_f32(size_t handle, uint64_t offset, float value) {
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)handle;
    if (buffer == NULL || !buffer->available || !buffer->host_visible || offset > buffer->size || buffer->size - offset < 4) return false;
    void *mapped = NULL;
    if (buffer->owner->map_memory(buffer->owner->device, buffer->memory, offset, 4, 0, &mapped) != VK_SUCCESS || mapped == NULL) return false;
    memcpy(mapped, &value, sizeof(value));
    buffer->owner->unmap_memory(buffer->owner->device, buffer->memory);
    return true;
}

uint32_t graphene_vk_buffer_read_u32(size_t handle, uint64_t offset) {
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)handle;
    if (buffer == NULL || !buffer->available || !buffer->host_visible || offset > buffer->size || sizeof(uint32_t) > buffer->size - offset) return 0;
    void *mapped = NULL;
    if (buffer->owner->map_memory(buffer->owner->device, buffer->memory, offset, sizeof(uint32_t), 0, &mapped) != VK_SUCCESS || mapped == NULL) return 0;
    uint32_t value = 0; memcpy(&value, mapped, sizeof(value));
    buffer->owner->unmap_memory(buffer->owner->device, buffer->memory);
    return value;
}

bool graphene_vk_buffer_destroy(size_t handle) {
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)handle;
    if (buffer == NULL) return false;
    if (buffer->owner != NULL && buffer->owner->device != NULL) {
        if (buffer->buffer != NULL) buffer->owner->destroy_buffer(buffer->owner->device, buffer->buffer, NULL);
        if (buffer->memory != NULL) buffer->owner->free_memory(buffer->owner->device, buffer->memory, NULL);
    }
    free(buffer);
    return true;
}

size_t graphene_vk_texture_create(size_t device_handle, uint32_t width, uint32_t height,
    uint32_t mip_levels, uint32_t format, uint32_t usage) {
    GrapheneVkDevice *device = (GrapheneVkDevice *)device_handle;
    GrapheneVkTexture *texture = (GrapheneVkTexture *)calloc(1, sizeof(GrapheneVkTexture));
    if (texture == NULL) return 0;
    texture->owner = device;
    texture->width = width;
    texture->height = height;
    texture->mip_levels = mip_levels;
    texture->format = format;
    texture->layout = VK_IMAGE_LAYOUT_UNDEFINED;
    texture->aspect = format == 126 ? VK_IMAGE_ASPECT_DEPTH_BIT : VK_IMAGE_ASPECT_COLOR_BIT;
    if (device == NULL || !device->available || width == 0 || height == 0 || mip_levels == 0 || format == 0 || usage == 0) {
        strncpy(texture->error, "Invalid GPU texture description", sizeof(texture->error) - 1); return (size_t)texture;
    }
    VkImageCreateInfo create_info = {
        VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, NULL, 0, 1, format, {width, height, 1},
        mip_levels, 1, 1, 0, usage, 0, 0, NULL, 0
    };
    if (device->create_image(device->device, &create_info, NULL, &texture->image) != VK_SUCCESS) {
        strncpy(texture->error, "Unable to create Vulkan image", sizeof(texture->error) - 1); return (size_t)texture;
    }
    VkMemoryRequirements requirements;
    device->get_image_requirements(device->device, texture->image, &requirements);
    uint32_t memory_type = graphene_memory_type(device, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (memory_type == UINT32_MAX) memory_type = graphene_memory_type(device, requirements.memoryTypeBits, 0);
    if (memory_type == UINT32_MAX) {
        strncpy(texture->error, "No compatible Vulkan image memory type", sizeof(texture->error) - 1); return (size_t)texture;
    }
    VkMemoryAllocateInfo allocate_info = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, requirements.size, memory_type};
    if (device->allocate_memory(device->device, &allocate_info, NULL, &texture->memory) != VK_SUCCESS) {
        strncpy(texture->error, "Unable to allocate Vulkan image memory", sizeof(texture->error) - 1); return (size_t)texture;
    }
    if (device->bind_image_memory(device->device, texture->image, texture->memory, 0) != VK_SUCCESS) {
        strncpy(texture->error, "Unable to bind Vulkan image memory", sizeof(texture->error) - 1); return (size_t)texture;
    }
    VkImageViewCreateInfo view_info = {
        VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, texture->image, 1, format,
        {0, 0, 0, 0}, {texture->aspect, 0, mip_levels, 0, 1}
    };
    if (device->create_image_view(device->device, &view_info, NULL, &texture->view) != VK_SUCCESS) {
        strncpy(texture->error, "Unable to create Vulkan image view", sizeof(texture->error) - 1); return (size_t)texture;
    }
    texture->available = true;
    return (size_t)texture;
}

bool graphene_vk_texture_available(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t != NULL && t->available; }
encore_str graphene_vk_texture_error(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return graphene_string(t == NULL ? "Invalid GPU texture" : t->error); }
uint32_t graphene_vk_texture_width(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t == NULL ? 0 : t->width; }
uint32_t graphene_vk_texture_height(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t == NULL ? 0 : t->height; }
uint32_t graphene_vk_texture_mip_levels(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t == NULL ? 0 : t->mip_levels; }
uint32_t graphene_vk_texture_format(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t == NULL ? 0 : t->format; }
uint32_t graphene_vk_texture_layout(size_t handle) { GrapheneVkTexture *t = (GrapheneVkTexture *)handle; return t == NULL ? 0 : t->layout; }

bool graphene_vk_texture_destroy(size_t handle) {
    GrapheneVkTexture *texture = (GrapheneVkTexture *)handle;
    if (texture == NULL) return false;
    if (texture->owner != NULL && texture->owner->device != NULL) {
        if (texture->view != NULL) texture->owner->destroy_image_view(texture->owner->device, texture->view, NULL);
        if (texture->image != NULL) texture->owner->destroy_image(texture->owner->device, texture->image, NULL);
        if (texture->memory != NULL) texture->owner->free_memory(texture->owner->device, texture->memory, NULL);
    }
    free(texture);
    return true;
}

static void graphene_layout_state(uint32_t layout, uint32_t *stage, uint32_t *access) {
    switch (layout) {
        case VK_IMAGE_LAYOUT_UNDEFINED: *stage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT; *access = 0; break;
        case VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL: *stage = VK_PIPELINE_STAGE_TRANSFER_BIT; *access = VK_ACCESS_TRANSFER_READ_BIT; break;
        case VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL: *stage = VK_PIPELINE_STAGE_TRANSFER_BIT; *access = VK_ACCESS_TRANSFER_WRITE_BIT; break;
        case VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL: *stage = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT; *access = VK_ACCESS_SHADER_READ_BIT; break;
        case VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL: *stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT; *access = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT; break;
        case VK_IMAGE_LAYOUT_DEPTH_STENCIL_ATTACHMENT_OPTIMAL: *stage = VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT; *access = VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT; break;
        default: *stage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT; *access = 0; break;
    }
}

bool graphene_vk_encoder_transition_texture(size_t encoder_handle, size_t texture_handle, uint32_t new_layout) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)encoder_handle;
    GrapheneVkTexture *texture = (GrapheneVkTexture *)texture_handle;
    if (encoder == NULL || !encoder->recording || texture == NULL || !texture->available || encoder->owner != texture->owner) return false;
    if (texture->layout == new_layout) return true;
    uint32_t source_stage, source_access, destination_stage, destination_access;
    graphene_layout_state(texture->layout, &source_stage, &source_access);
    graphene_layout_state(new_layout, &destination_stage, &destination_access);
    VkImageMemoryBarrier barrier = {
        VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL, source_access, destination_access,
        texture->layout, new_layout, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED,
        texture->image, {texture->aspect, 0, texture->mip_levels, 0, 1}
    };
    encoder->owner->cmd_pipeline_barrier(encoder->command_buffer, source_stage, destination_stage, 0,
        0, NULL, 0, NULL, 1, &barrier);
    texture->layout = new_layout;
    return true;
}

bool graphene_vk_encoder_copy_buffer_to_texture(size_t encoder_handle, size_t buffer_handle,
    size_t texture_handle, uint32_t width, uint32_t height, uint32_t mip_level) {
    GrapheneVkEncoder *encoder = (GrapheneVkEncoder *)encoder_handle;
    GrapheneVkBuffer *buffer = (GrapheneVkBuffer *)buffer_handle;
    GrapheneVkTexture *texture = (GrapheneVkTexture *)texture_handle;
    if (encoder == NULL || !encoder->recording || buffer == NULL || !buffer->available || texture == NULL ||
        !texture->available || encoder->owner != buffer->owner || encoder->owner != texture->owner ||
        texture->layout != VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL || width == 0 || height == 0 ||
        width > texture->width || height > texture->height || mip_level >= texture->mip_levels ||
        buffer->size < (uint64_t)width * (uint64_t)height * 4u) return false;
    VkBufferImageCopy region = {
        0, 0, 0, {texture->aspect, mip_level, 0, 1}, {0, 0, 0}, {width, height, 1}
    };
    encoder->owner->cmd_copy_buffer_to_image(encoder->command_buffer, buffer->buffer, texture->image,
        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);
    return true;
}
