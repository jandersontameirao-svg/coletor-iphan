# Contratos 0.4 — conhecimento e geografia

Todas as rotas exigem `Authorization: Bearer <token>` e aplicam a ACL do processo. Os exemplos abaixo usam IDs de teste.

## Afirmação rastreável

```http
POST /v1/knowledge/assertions
Authorization: Bearer <token>
Content-Type: application/json
```

```json
{
  "process_id": "<processo autorizado>",
  "evidence_id": "<evidência autorizada>",
  "statement": "Trecho técnico registrado após leitura da fonte.",
  "kind": "fact",
  "confidence": 0.8
}
```

A resposta inicial é `proposed`. Somente usuário com `review` pode alterar para `validated`, `rejected` ou `conflict`. A evidência, revisão, documento e processo permanecem no registro. Nenhum texto é criado automaticamente.

## Relação entre afirmações

```json
{
  "related_id": "<outra afirmação no mesmo processo>",
  "relation": "contradicts"
}
```

Relações aceitas: `supports`, `contradicts` e `derived_from`.

## Recurso KML/KMZ

```http
POST /v1/spatial-resources?process_id=<id>&name=Area%20de%20pesquisa&filename=area.kml
Authorization: Bearer <token>
Content-Type: application/vnd.google-earth.kml+xml
```

O corpo é binário KML/KMZ. O recurso é gravado como revisão geométrica versionada, com hash da fonte, WGS84/EPSG:4326 e feições normalizadas. O arquivo não é publicado nem duplicado automaticamente no acervo documental.

## Pesquisa por entorno

```json
{
  "process_id": "<processo autorizado>",
  "latitude": -15.0,
  "longitude": -48.0,
  "radius_m": 5000
}
```

`POST /v1/spatial-search` retorna `distance_m` e `units: "metres"`. A distância é geodésica; graus não são usados como metros. O resultado mantém processo, recurso, versão, feição, papel e precisão informados.

## Capacidades de integração

`GET /v1/integration/capabilities` informa que os contratos locais de conhecimento e geografia existem, mas `atena_real_homologated` e `geoportal_real_homologated` continuam `false`. Isso é intencional até existir acesso autorizado e evidência externa verificável.
