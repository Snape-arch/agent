"""Public contract for the first classification evaluation workflow."""


def schemas():
    return {
        "EvaluationSample": {"type": "object", "required": ["id", "label"], "properties": {
            "id": {"type": "string", "minLength": 1, "maxLength": 128},
            "label": {"type": "string", "minLength": 1, "maxLength": 128},
            "conditions": {"type": "object", "maxProperties": 8, "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 128}},
            "imageUri": {"type": ["string", "null"], "maxLength": 2048},
            "contentHash": {"type": ["string", "null"], "pattern": "^[a-fA-F0-9]{64}$"}}},
        "CreateEvaluationTestSet": {"type": "object", "required": ["name", "samples"], "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 200},
            "task": {"type": "string", "enum": ["classification"], "default": "classification"},
            "classes": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True, "items": {"type": "string", "minLength": 1, "maxLength": 128}},
            "datasetVersionId": {"type": "string"},
            "samples": {"type": "array", "minItems": 1, "maxItems": 5000, "items": {"$ref": "#/components/schemas/EvaluationSample"}}}},
        "CreateEvaluationReport": {"type": "object", "required": ["testSetId", "runId", "predictions"], "properties": {
            "testSetId": {"type": "string"}, "runId": {"type": "string"}, "modelArtifactId": {"type": "string"},
            "name": {"type": "string", "maxLength": 200},
            "predictions": {"type": "array", "minItems": 1, "maxItems": 5000, "items": {
                "type": "object", "required": ["sampleId", "label"], "properties": {
                    "sampleId": {"type": "string"}, "label": {"type": "string"},
                    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1}}}}}},
    }


def paths():
    page = [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
            {"name": "pageSize", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}}]

    def read(operation, parameters=None, description="Evaluation evidence"):
        return {"operationId": operation, "parameters": parameters or [], "responses": {"200": {"description": description}, "404": {"description": "Tenant resource not found"}}}

    def write(operation, schema):
        return {"operationId": operation, "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}}},
                "responses": {"201": {"description": "Immutable record created"}, "400": {"description": "Invalid manifest or incomplete predictions"}, "403": {"description": "Researcher role and write scope required"}}}

    def parameter(name, location="query", required=False):
        return {"name": name, "in": location, "required": required, "schema": {"type": "string"}}

    return {
        "/api/evaluation/test-sets": {"get": read("listEvaluationTestSets", page), "post": write("createEvaluationTestSet", "CreateEvaluationTestSet")},
        "/api/evaluation/test-sets/{testSetId}": {"get": read("getEvaluationTestSet", [parameter("testSetId", "path", True)])},
        "/api/evaluation/test-sets/{testSetId}/export": {"get": read("exportEvaluationTestSet", [parameter("testSetId", "path", True)], "Frozen manifest with samples and SHA-256 digest")},
        "/api/evaluation/reports": {"get": read("listEvaluationReports", [*page, parameter("testSetId")]), "post": write("createEvaluationReport", "CreateEvaluationReport")},
        "/api/evaluation/reports/{evaluationId}": {"get": read("getEvaluationReport", [parameter("evaluationId", "path", True)])},
        "/api/evaluation/reports/{evaluationId}/cases": {"get": read("listEvaluationCases", [parameter("evaluationId", "path", True), *page,
            {"name": "failuresOnly", "in": "query", "schema": {"type": "boolean", "default": True}}, parameter("dimension"), parameter("value")])},
        "/api/evaluation/compare": {"get": read("compareEvaluations", [parameter("baselineId", required=True), parameter("candidateId", required=True)], "Paired comparison of two Runs on the same frozen test set")},
    }
