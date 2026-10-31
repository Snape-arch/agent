"""Shared HTTP contract helpers and the machine-readable API description."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence
from evaluation_contract import paths as evaluation_paths, schemas as evaluation_schemas
from scenario_contract import paths as scenario_paths, schemas as scenario_schemas
from synthesis_contract import paths as synthesis_paths, schemas as synthesis_schemas
from vision_contract import paths as vision_paths, schemas as vision_schemas


@dataclass(frozen=True)
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def parse_pagination(query: Mapping[str, Sequence[str]], *, default: int = 100, maximum: int = 500) -> Pagination:
    """Parse bounded, one-based pagination parameters."""
    try:
        page = int((query.get("page") or ["1"])[0])
        page_size = int((query.get("pageSize") or [str(default)])[0])
    except (TypeError, ValueError) as error:
        raise ValueError("page and pageSize must be integers") from error
    if page < 1:
        raise ValueError("page must be at least 1")
    if page_size < 1 or page_size > maximum:
        raise ValueError(f"pageSize must be between 1 and {maximum}")
    return Pagination(page, page_size)


def page_meta(pagination: Pagination, total: int) -> dict:
    pages = (total + pagination.page_size - 1) // pagination.page_size
    return {
        "page": pagination.page,
        "pageSize": pagination.page_size,
        "total": total,
        "pages": pages,
        "hasNext": pagination.page < pages,
        "hasPrevious": pagination.page > 1,
    }


def openapi_document(version: str) -> dict:
    """Return the public v1 surface. Complex bodies intentionally stay extensible."""
    page_parameters = [
        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
        {"name": "pageSize", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}},
    ]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ClawVision API",
            "version": version,
            "description": "Experiment tracking, visualization, AI 3D Studio and durable worker API.",
        },
        "servers": [{"url": "/"}],
        "paths": {
            **evaluation_paths(),
            **scenario_paths(),
            **synthesis_paths(),
            **vision_paths(),
            "/api/health": {"get": {"operationId": "health", "responses": {"200": {"description": "Service health"}}}},
            "/api/runs": {
                "get": {"operationId": "listRuns", "parameters": [*page_parameters, {"name": "summary", "in": "query", "description": "Set to 1 for metadata, latestMetric and counts without histories or artifact content", "schema": {"type": "string", "enum": ["0", "1"], "default": "0"}}, {"name": "q", "in": "query", "description": "Case-insensitive literal substring of name within the authenticated tenant", "schema": {"type": "string", "maxLength": 200}}], "responses": {"200": {"description": "Paginated runs with tenant-wide status counts"}}},
                "post": {"operationId": "createRun", "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateRun"}}}}, "responses": {"201": {"description": "Run created"}}},
            },
            "/api/runs/{runId}": {
                "get": {"operationId": "getRun", "parameters": [{"name": "runId", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Full consistent snapshot including events and durable cursor"}, "404": {"description": "Run not found in tenant"}}}
            },
            "/api/runs/{runId}/changes": {
                "get": {"operationId": "getRunChanges", "parameters": [{"name": "runId", "in": "path", "required": True, "schema": {"type": "string"}}, {"name": "after", "in": "query", "schema": {"type": "integer", "minimum": 0, "default": 0}}, {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}}], "responses": {"200": {"description": "Changed metrics/events/artifacts, removed keys, metadata, cursor and hasMore"}, "400": {"description": "Invalid or ahead-of-snapshot cursor"}}}
            },
            "/api/runs/{runId}/stream": {
                "get": {"operationId": "streamRun", "parameters": [{"name": "runId", "in": "path", "required": True, "schema": {"type": "string"}}, {"name": "incremental", "in": "query", "schema": {"type": "string", "enum": ["0", "1"], "default": "0"}}, {"name": "after", "in": "query", "schema": {"type": "integer", "minimum": 0}}, {"name": "Last-Event-ID", "in": "header", "schema": {"type": "integer", "minimum": 0}}], "responses": {"200": {"description": "Legacy run snapshots or incremental run-delta events; id is the durable cursor", "content": {"text/event-stream": {"schema": {"type": "string"}}}}}}
            },
            "/api/runs/{runId}/resume": {
                "post": {"operationId": "resumeRun", "responses": {"200": {"description": "Resume a failed or interrupted run from a checkpoint"}}}
            },
            "/api/datasets": {
                "get": {"operationId": "listDatasets", "parameters": page_parameters, "responses": {"200": {"description": "Paginated datasets"}}},
                "post": {"operationId": "createDataset", "responses": {"201": {"description": "Dataset imported"}}},
            },
            "/api/datasets/{datasetId}/query": {
                "post": {
                    "operationId": "queryDataset",
                    "parameters": [{"name": "datasetId", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Filtered and aggregated data"}},
                }
            },
            "/api/datasets/{datasetId}/versions": {
                "get": {"operationId": "listDatasetVersions", "parameters": [*page_parameters, {"name": "datasetId", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Versioned manifests and schema changes"}}},
                "post": {"operationId": "createDatasetVersion", "responses": {"201": {"description": "Dataset version created"}}},
            },
            "/api/datasets/{datasetId}/lineage": {
                "get": {"operationId": "getDatasetLineage", "responses": {"200": {"description": "Upstream and downstream lineage"}}}
            },
            "/api/analysis/query": {
                "post": {"operationId": "executeAnalysisQuery", "responses": {"200": {"description": "Cross-dataset query result and physical plan"}}}
            },
            "/api/analysis/queries": {
                "get": {"operationId": "listAnalysisQueries", "parameters": page_parameters, "responses": {"200": {"description": "Paginated query history"}}},
                "post": {"operationId": "submitAnalysisQuery", "responses": {"202": {"description": "Cancellable query queued"}}},
            },
            "/api/analysis/queries/{queryId}": {
                "get": {"operationId": "getAnalysisQuery", "responses": {"200": {"description": "Query state and result"}}}
            },
            "/api/analysis/queries/{queryId}/cancel": {
                "post": {"operationId": "cancelAnalysisQuery", "responses": {"202": {"description": "Cancellation requested"}}}
            },
            "/api/model-assets": {
                "get": {"operationId": "listModelAssets", "parameters": page_parameters, "responses": {"200": {"description": "Paginated model assets"}}},
                "post": {"operationId": "createModelAsset", "responses": {"201": {"description": "Asset created"}}},
            },
            "/api/model-assets/{assetId}/stream-manifest": {"get": {"operationId": "getModelAssetStreamManifest", "responses": {"200": {"description": "Byte size, format and authenticated streaming URL"}}}},
            "/api/model-assets/{assetId}/content": {"get": {"operationId": "streamModelAsset", "parameters": [{"name":"Range","in":"header","schema":{"type":"string"}}], "responses": {"200": {"description":"Complete asset"}, "206": {"description": "Byte range"}}}},
            "/api/telemetry/3d": {
                "get": {"operationId":"list3DTelemetry","parameters":page_parameters,"responses":{"200":{"description":"Paginated browser GPU and scene telemetry"}}},
                "post": {"operationId":"record3DTelemetry","responses":{"201":{"description":"Telemetry sample recorded"}}},
            },
            "/api/studio/text-to-3d": {"post": {"operationId": "createTextTo3DJob", "responses": {"201": {"description": "Job queued"}}}},
        },
        "components": {
            "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
            "schemas": {
                **evaluation_schemas(),
                **scenario_schemas(),
                **synthesis_schemas(),
                **vision_schemas(),
                "CreateRun": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string", "minLength": 1},
                        "params": {"type": "object", "additionalProperties": True},
                        "source": {"type": "string"},
                    },
                },
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {"type": "string"},
                        "code": {"type": "string"},
                        "requestId": {"type": "string"},
                    },
                },
            },
        },
        "security": [{"bearerAuth": []}],
    }
