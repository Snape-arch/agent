"""Public contract for immutable, unrendered scene plans."""


def schemas():
    bounds = {"cameraAzimuth": [-180, 180], "cameraElevation": [-80, 80], "cameraDistance": [1.5, 10],
              "lightAzimuth": [-180, 180], "lightElevation": [-80, 80], "lightIntensity": [0, 10],
              "roughness": [0, 1], "metalness": [0, 1], "occluderSize": [0, 1.5]}
    return {
        "ScenePlanConfig": {"type": "object", "additionalProperties": False, "properties": {
            "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295, "default": 42},
            "count": {"type": "integer", "minimum": 1, "maximum": 256, "default": 12},
            "materialColor": {"type": "string", "pattern": "^#[a-fA-F0-9]{6}$", "default": "#7cf7c8"},
            "background": {"type": "string", "pattern": "^#[a-fA-F0-9]{6}$", "default": "#152620"},
            "ranges": {"type": "object", "additionalProperties": False, "properties": {
                key: {"type": "array", "minItems": 2, "maxItems": 2,
                      "items": {"type": "number", "minimum": low, "maximum": high},
                      "description": "Ordered [minimum,maximum], rounded to six decimal places"}
                for key, (low, high) in bounds.items()}}}},
        "CreateScenePlan": {"type": "object", "additionalProperties": False,
                            "required": ["name", "reportId", "sampleId", "assetId", "label"], "properties": {
            **{key: {"type": "string", "minLength": 1, "maxLength": 128} for key in ("reportId", "sampleId", "assetId", "label", "parentId")},
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "config": {"$ref": "#/components/schemas/ScenePlanConfig"}}},
    }


def paths():
    identifier = {"name": "scenarioId", "in": "path", "required": True, "schema": {"type": "string"}}
    def read(operation, parameters):
        return {"operationId": operation, "parameters": parameters, "responses": {
            "200": {"description": "Immutable scene evidence"}, "404": {"description": "Tenant resource not found"},
            "409": {"description": "Pinned asset missing or hash mismatch"}}}
    return {
        "/api/evaluation/scenarios": {
            "get": read("listScenePlans", [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                {"name": "pageSize", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}},
                {"name": "reportId", "in": "query", "schema": {"type": "string"}}]),
            "post": {"operationId": "createScenePlan", "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/CreateScenePlan"}}}}, "responses": {
                    "201": {"description": "Immutable plan created; no rendered images or annotations"},
                    "400": {"description": "Invalid bounds, mismatched label, unsupported format or asset over 16 MB"},
                    "403": {"description": "Researcher and write scope required"}, "404": {"description": "Tenant resource not found"}}}},
        "/api/evaluation/scenarios/{scenarioId}": {"get": read("getScenePlan", [identifier])},
        "/api/evaluation/scenarios/{scenarioId}/export": {"get": read("exportScenePlan", [identifier])},
        "/api/evaluation/scenarios/{scenarioId}/asset": {"get": read("getVerifiedSceneAsset", [identifier])},
    }
