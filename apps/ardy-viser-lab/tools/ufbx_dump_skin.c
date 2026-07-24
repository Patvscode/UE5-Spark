// SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
// SPDX-License-Identifier: MIT
//
// Small ufbx front-end used by fbx_to_wardrobe.py. It intentionally writes a
// simple private interchange directory instead of trying to implement NPZ in C.

#include "ufbx.h"

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>

static void die(const char *message)
{
    fprintf(stderr, "ufbx_dump_skin: %s\n", message);
    exit(1);
}

static void die_errno(const char *path)
{
    fprintf(stderr, "ufbx_dump_skin: %s: %s\n", path, strerror(errno));
    exit(1);
}

static FILE *open_output(const char *root, const char *name, const char *mode)
{
    char path[4096];
    int count = snprintf(path, sizeof(path), "%s/%s", root, name);
    if (count < 0 || (size_t)count >= sizeof(path)) die("output path is too long");
    FILE *file = fopen(path, mode);
    if (!file) die_errno(path);
    return file;
}

static void write_all(FILE *file, const void *data, size_t item_size, size_t count)
{
    if (count > 0 && fwrite(data, item_size, count, file) != count) {
        die("failed to write output array");
    }
}

static void print_tsv_string(FILE *file, ufbx_string value)
{
    for (size_t i = 0; i < value.length; ++i) {
        char ch = value.data[i];
        if (ch == '\t' || ch == '\r' || ch == '\n') ch = '_';
        fputc(ch, file);
    }
}

static void matrix_to_row_major(float dst[16], const ufbx_matrix *src)
{
    dst[0] = (float)src->m00;
    dst[1] = (float)src->m01;
    dst[2] = (float)src->m02;
    dst[3] = (float)src->m03;
    dst[4] = (float)src->m10;
    dst[5] = (float)src->m11;
    dst[6] = (float)src->m12;
    dst[7] = (float)src->m13;
    dst[8] = (float)src->m20;
    dst[9] = (float)src->m21;
    dst[10] = (float)src->m22;
    dst[11] = (float)src->m23;
    dst[12] = 0.0f;
    dst[13] = 0.0f;
    dst[14] = 0.0f;
    dst[15] = 1.0f;
}

static int string_equals_cstr(ufbx_string value, const char *expected)
{
    size_t length = strlen(expected);
    return value.length == length && memcmp(value.data, expected, length) == 0;
}

static ufbx_mesh *find_mesh(ufbx_scene *scene, const char *requested)
{
    ufbx_mesh *fallback = NULL;
    for (size_t i = 0; i < scene->meshes.count; ++i) {
        ufbx_mesh *mesh = scene->meshes.data[i];
        if (mesh->skin_deformers.count == 0) continue;
        if (!fallback) fallback = mesh;
        if (requested && string_equals_cstr(mesh->name, requested)) return mesh;
    }
    return requested ? NULL : fallback;
}

int main(int argc, char **argv)
{
    if (argc < 3 || argc > 4) {
        fprintf(stderr, "usage: %s INPUT.fbx OUTPUT_DIR [MESH_NAME]\n", argv[0]);
        return 2;
    }

    const char *input_path = argv[1];
    const char *output_root = argv[2];
    const char *mesh_name = argc == 4 ? argv[3] : NULL;

    if (mkdir(output_root, 0700) != 0 && errno != EEXIST) die_errno(output_root);

    ufbx_load_opts opts = { 0 };
    opts.generate_missing_normals = true;
    opts.target_axes.right = UFBX_COORDINATE_AXIS_POSITIVE_X;
    opts.target_axes.up = UFBX_COORDINATE_AXIS_POSITIVE_Y;
    opts.target_axes.front = UFBX_COORDINATE_AXIS_POSITIVE_Z;
    opts.target_unit_meters = 1.0;

    ufbx_error error;
    ufbx_scene *scene = ufbx_load_file(input_path, &opts, &error);
    if (!scene) {
        fprintf(stderr, "ufbx_dump_skin: could not load %s: %s\n",
            input_path, error.description.data ? error.description.data : "unknown ufbx error");
        return 1;
    }

    ufbx_mesh *mesh = find_mesh(scene, mesh_name);
    if (!mesh) {
        fprintf(stderr, "ufbx_dump_skin: no matching skinned mesh found");
        if (mesh_name) fprintf(stderr, " for '%s'", mesh_name);
        fputc('\n', stderr);
        ufbx_free_scene(scene);
        return 1;
    }
    if (mesh->instances.count == 0) die("selected mesh has no scene instance");

    ufbx_node *mesh_node = mesh->instances.data[0];
    ufbx_skin_deformer *skin = mesh->skin_deformers.data[0];
    const size_t vertex_count = mesh->num_vertices;
    const size_t triangle_count = mesh->num_triangles;
    const size_t bone_count = skin->clusters.count;
    size_t influence_count = skin->max_weights_per_vertex;
    if (influence_count == 0) influence_count = 1;

    if (vertex_count == 0 || triangle_count == 0 || bone_count == 0) {
        die("selected mesh has empty geometry or skin data");
    }

    float *vertices = (float *)calloc(vertex_count * 3, sizeof(float));
    uint32_t *faces = (uint32_t *)calloc(triangle_count * 3, sizeof(uint32_t));
    int32_t *indices = (int32_t *)malloc(vertex_count * influence_count * sizeof(int32_t));
    float *weights = (float *)calloc(vertex_count * influence_count, sizeof(float));
    float *bind_matrices = (float *)calloc(bone_count * 16, sizeof(float));
    uint32_t *tri_indices = (uint32_t *)malloc(mesh->max_face_triangles * 3 * sizeof(uint32_t));
    if (!vertices || !faces || !indices || !weights || !bind_matrices || !tri_indices) {
        die("out of memory");
    }
    for (size_t i = 0; i < vertex_count * influence_count; ++i) indices[i] = -1;

    for (size_t i = 0; i < vertex_count; ++i) {
        ufbx_vec3 position = ufbx_transform_position(&mesh_node->geometry_to_world, mesh->vertices.data[i]);
        vertices[i * 3 + 0] = (float)position.x;
        vertices[i * 3 + 1] = (float)position.y;
        vertices[i * 3 + 2] = (float)position.z;
    }

    size_t triangle_cursor = 0;
    for (size_t face_index = 0; face_index < mesh->faces.count; ++face_index) {
        ufbx_face face = mesh->faces.data[face_index];
        size_t face_triangles = ufbx_triangulate_face(
            tri_indices, mesh->max_face_triangles * 3, mesh, face);
        for (size_t i = 0; i < face_triangles * 3; ++i) {
            uint32_t corner_index = tri_indices[i];
            if (corner_index >= mesh->vertex_indices.count) die("triangulation produced an invalid corner");
            uint32_t vertex_index = mesh->vertex_indices.data[corner_index];
            if (vertex_index >= vertex_count) die("face references an invalid logical vertex");
            faces[triangle_cursor * 3 + i] = vertex_index;
        }
        triangle_cursor += face_triangles;
    }
    if (triangle_cursor != triangle_count) die("triangle count changed during triangulation");

    for (size_t vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
        ufbx_skin_vertex vertex_skin = skin->vertices.data[vertex_index];
        if (vertex_skin.num_weights > influence_count) die("ufbx skin influence count is inconsistent");
        for (size_t i = 0; i < vertex_skin.num_weights; ++i) {
            ufbx_skin_weight influence = skin->weights.data[vertex_skin.weight_begin + i];
            if (influence.cluster_index >= bone_count) die("skin influence references an invalid cluster");
            size_t output_index = vertex_index * influence_count + i;
            indices[output_index] = (int32_t)influence.cluster_index;
            weights[output_index] = (float)influence.weight;
        }
    }

    FILE *bones_file = open_output(output_root, "bones.tsv", "wb");
    fprintf(bones_file, "index\tname\tparent\n");
    for (size_t i = 0; i < bone_count; ++i) {
        ufbx_skin_cluster *cluster = skin->clusters.data[i];
        matrix_to_row_major(&bind_matrices[i * 16], &cluster->bind_to_world);
        fprintf(bones_file, "%zu\t", i);
        print_tsv_string(bones_file, cluster->bone_node->name);
        fputc('\t', bones_file);
        if (cluster->bone_node->parent) print_tsv_string(bones_file, cluster->bone_node->parent->name);
        fputc('\n', bones_file);
    }
    fclose(bones_file);

    FILE *nodes_file = open_output(output_root, "nodes.tsv", "wb");
    fprintf(nodes_file, "name\tparent\tis_bone");
    for (size_t i = 0; i < 16; ++i) fprintf(nodes_file, "\tm%zu", i);
    fputc('\n', nodes_file);
    for (size_t i = 0; i < scene->nodes.count; ++i) {
        ufbx_node *node = scene->nodes.data[i];
        float matrix[16];
        matrix_to_row_major(matrix, &node->node_to_world);
        print_tsv_string(nodes_file, node->name);
        fputc('\t', nodes_file);
        if (node->parent) print_tsv_string(nodes_file, node->parent->name);
        fprintf(nodes_file, "\t%d", node->bone != NULL ? 1 : 0);
        for (size_t j = 0; j < 16; ++j) fprintf(nodes_file, "\t%.9g", matrix[j]);
        fputc('\n', nodes_file);
    }
    fclose(nodes_file);

    FILE *file = open_output(output_root, "vertices.f32", "wb");
    write_all(file, vertices, sizeof(float), vertex_count * 3);
    fclose(file);
    file = open_output(output_root, "faces.u32", "wb");
    write_all(file, faces, sizeof(uint32_t), triangle_count * 3);
    fclose(file);
    file = open_output(output_root, "influence_indices.i32", "wb");
    write_all(file, indices, sizeof(int32_t), vertex_count * influence_count);
    fclose(file);
    file = open_output(output_root, "influence_weights.f32", "wb");
    write_all(file, weights, sizeof(float), vertex_count * influence_count);
    fclose(file);
    file = open_output(output_root, "bind_matrices.f32", "wb");
    write_all(file, bind_matrices, sizeof(float), bone_count * 16);
    fclose(file);

    FILE *metadata = open_output(output_root, "metadata.txt", "wb");
    fprintf(metadata, "schema_version=1\n");
    fprintf(metadata, "vertex_count=%zu\n", vertex_count);
    fprintf(metadata, "triangle_count=%zu\n", triangle_count);
    fprintf(metadata, "bone_count=%zu\n", bone_count);
    fprintf(metadata, "influence_count=%zu\n", influence_count);
    fprintf(metadata, "mesh_name=");
    print_tsv_string(metadata, mesh->name);
    fputc('\n', metadata);
    fprintf(metadata, "coordinate_system=right-handed-y-up-z-forward-meters\n");
    fclose(metadata);

    free(vertices);
    free(faces);
    free(indices);
    free(weights);
    free(bind_matrices);
    free(tri_indices);
    ufbx_free_scene(scene);

    fprintf(stdout,
        "UFBX_SKIN_DUMP_OK vertices=%zu triangles=%zu bones=%zu influences=%zu\n",
        vertex_count, triangle_count, bone_count, influence_count);
    return 0;
}
