"""Image version and controlled CPU comparison routes."""
def schemas():
    return {
        "CreateImageDataset":{"type":"object","required":["name","purpose","samples"],"additionalProperties":False,"properties":{
            "name":{"type":"string"},"datasetId":{"type":"string"},"purpose":{"enum":["train","test"]},
            "samples":{"type":"array","minItems":1,"maxItems":512,"items":{"type":"object","required":["id","label","imageBase64"],"additionalProperties":False,"properties":{
                "id":{"type":"string"},"label":{"type":"string"},"imageBase64":{"type":"string","contentEncoding":"base64"},"conditions":{"type":"object","additionalProperties":{"type":"string"}}}}}}},
        "RegisterSynthesisDataset":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"datasetId":{"type":"string"}}},
        "CreateVisionExperiment":{"type":"object","required":["realTrainVersionId","syntheticVersionId","testVersionId"],"additionalProperties":False,"properties":{
            **{k:{"type":"string"} for k in ("realTrainVersionId","syntheticVersionId","testVersionId")},
            "config":{"type":"object","additionalProperties":False,"properties":{"seed":{"type":"integer","minimum":0,"maximum":2**32-1},"epochs":{"type":"integer","minimum":1,"maximum":200},"learningRate":{"type":"number","minimum":.0001,"maximum":1},"regularization":{"type":"number","minimum":0,"maximum":1}}}}}}

def paths():
    definitions = [
        ("/image-datasets","post","createImageDataset","CreateImageDataset"),
        ("/image-versions","get","listImageVersions",None),
        ("/image-versions/{versionId}","get","getImageVersion",None),
        ("/image-versions/{versionId}/images/{index}","get","getVersionImage",None),
        ("/synthesis/{jobId}/dataset-version","post","registerSynthesisDataset","RegisterSynthesisDataset"),
        ("/experiments","get","listVisionExperiments",None),
        ("/experiments","post","createVisionExperiment","CreateVisionExperiment"),
        ("/experiments/{experimentId}","get","getVisionExperiment",None),
        ("/experiments/{experimentId}/cancel","post","cancelVisionExperiment",None),
        ("/experiments/{experimentId}/retry","post","retryVisionExperiment",None)]
    result = {}
    for path,method,name,schema in definitions:
        status = "202" if method=="post" and "Experiment" in name else "201" if method=="post" else "200"
        spec = {"operationId":name,"parameters":[{"name":k,"in":"path","required":True,"schema":{"type":"integer","minimum":0} if k=="index" else {"type":"string"}} for k in ("versionId","index","jobId","experimentId") if "{"+k+"}" in path],
                "responses":{status:{"description":"Success"},"400":{"description":"Invalid data or leakage"},"403":{"description":"Permission or quota denied"},"404":{"description":"Resource not visible"},"409":{"description":"Pinned data changed"}}}
        if method=="get" and path in {"/experiments","/image-versions"}:
            spec["parameters"] += [{"name":k,"in":"query","schema":{"type":"integer","minimum":1,"maximum":100 if k=="pageSize" else 1000000}} for k in ("page","pageSize")]
        if schema: spec["requestBody"] = {"required":True,"content":{"application/json":{"schema":{"$ref":"#/components/schemas/"+schema}}}}
        if name=="getVersionImage": spec["responses"]["200"]["content"] = {"image/png":{"schema":{"type":"string","format":"binary"}}}
        result.setdefault("/api/evaluation"+path,{})[method] = spec
    return result
