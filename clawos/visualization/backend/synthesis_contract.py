"""HTTP contract for CPU rendering and geometry-derived synthetic labels."""


def schemas():
    return {"CreateSynthesisJob": {"type": "object", "additionalProperties": False, "properties": {
        "variantIndices": {"type": "array", "minItems": 1, "maxItems": 64, "uniqueItems": True, "items": {"type": "integer", "minimum": 0, "maximum": 255}},
        "minVisiblePixels": {"type": "integer", "minimum": 1, "maximum": 262144, "default": 64},
        "minVisibleFraction": {"type": "number", "minimum": 0, "maximum": 1, "default": .2},
        "rejectClipped": {"type": "boolean", "default": True}}}}


def paths():
    def parameter(name, location="path", maximum=None):
        schema = {"type": "integer", "minimum": 1, **({"maximum": maximum} if maximum else {})} if location == "query" else {"type": "string"}
        return {"name": name, "in": location, "required": location == "path", "schema": schema}
    def read(operation, parameters, mime="application/json"):
        return {"operationId": operation, "parameters": parameters, "responses": {
            "200": {"description": "Tenant-scoped rendered artifacts", "content": {mime: {"schema": {"type": "string", "format": "binary"} if mime != "application/json" else {"type": "object"}}}},
            "404": {"description": "Resource not visible"}, "409": {"description": "Incomplete dataset or artifact hash mismatch"}}}
    job = parameter("jobId")
    page = [parameter("page", "query"), parameter("pageSize", "query", 100)]
    write = {"responses": {"202": {"description": "Durable task queued or existing immutable job returned"},
                           "400": {"description": "Invalid render options or missing CPU provider"},
                           "403": {"description": "Researcher and write scope required"}, "404": {"description": "Tenant resource not found"}}}
    return {
        "/api/evaluation/scenarios/{scenarioId}/renders": {
            "get": read("listSynthesisJobs", [parameter("scenarioId"), *page]),
            "post": {**write, "operationId": "createSynthesisJob", "parameters": [parameter("scenarioId")], "requestBody": {
                "required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateSynthesisJob"}}}}}},
        "/api/evaluation/synthesis/{jobId}": {"get": read("getSynthesisJob", [job])},
        "/api/evaluation/synthesis/{jobId}/frames": {"get": read("listSyntheticFrames", [job, *page])},
        "/api/evaluation/synthesis/{jobId}/manifest": {"get": read("getSyntheticManifest", [job])},
        "/api/evaluation/synthesis/{jobId}/export": {"get": read("exportSyntheticDataset", [job], "application/zip")},
        "/api/evaluation/synthesis/{jobId}/frames/{index}/{kind}": {"get": read("getSyntheticPng", [job,
            {"name": "index", "in": "path", "required": True, "schema": {"type": "integer", "minimum": 0, "maximum": 255}},
            {"name": "kind", "in": "path", "required": True, "schema": {"type": "string", "enum": ["image", "mask", "amodalMask"]}}], "image/png")},
        **{f"/api/evaluation/synthesis/{{jobId}}/{action}": {"post": {**write, "operationId": action+"SynthesisJob", "parameters": [job]}} for action in ("cancel", "retry")},
    }
