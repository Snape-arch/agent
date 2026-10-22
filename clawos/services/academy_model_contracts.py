"""Small decoder schemas; source, ownership, CAS and DAG checks stay local."""
def obj(properties):
    return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)


def graph_contract(graph):
    selected=set(graph['selected_chapters'])
    citations=sorted({s['citation'] for c in graph['index']['chapters'] if c['id'] in selected for s in c['sources']})
    text=dict(type='string')
    def reference_for(chapter=None):
        choices={}
        for row in graph.get('quote_choices',[]):
            if chapter is not None and row.get('chapter')!=chapter:continue
            choices.setdefault(row['citation'],[])
            choices[row['citation']]+= [q for q in row['quotes'] if q not in choices[row['citation']]]
        return dict(anyOf=[obj(dict(citation=dict(type='string',enum=[citation]),quote=dict(type='string',enum=quotes))) for citation,quotes in choices.items() if quotes]) if any(choices.values()) else None
    reference=reference_for() or obj(dict(citation=dict(type='string',enum=citations),quote=text))
    branches=[]
    for chapter in sorted(selected):
        source=reference_for(chapter)
        if source:branches.append(obj(dict(id=text,title=text,chapter=dict(type='string',enum=[chapter]),explanation=text,source=source)))
    node=dict(anyOf=branches) if branches else obj(dict(id=text,title=text,chapter=text,explanation=text,source=reference))
    edge=obj({'from':text,'to':text,'kind':dict(type='string',enum=['prerequisite','related','supports','contrasts']),
              'status':dict(type='string',enum=['proposed']),'reason':text,'source':reference})
    return obj(dict(nodes=dict(type='array',items=node,maxItems=6 if branches else 0),edges=dict(type='array',items=edge,maxItems=4),
                    covered_chapters=dict(type='array',items=dict(type='string',enum=sorted(selected)))))


def review_contract():
    text=dict(type='string')
    dimension=obj(dict(score=dict(type='integer',enum=[0,1,2]),reason=text,student_quote=text,source_quote=text,next_step=text))
    return obj(dict(dimensions=obj({d:dimension for d in ('concept','reasoning','transfer')})))


def options(schema,name):
    return dict(temperature=0.0,max_tokens=2800,response_format=dict(type='json_schema',json_schema=dict(name=name,strict=True,schema=schema)))
