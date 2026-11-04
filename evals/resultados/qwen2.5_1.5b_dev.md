# Bateria do intérprete — `qwen2.5:1.5b` — dev

03/11/2026 22:37 · temperatura 0

**Acerto: 23/27 (85%)** · tempo médio 5 s · campos inventados descartados pela conferência: 4

| Grupo | Acerto |
|---|---|
| acessorio | 1/2 |
| conversa | 2/2 |
| fora_de_escopo | 2/3 |
| multiplo | 1/1 |
| nao_recusar | 3/3 |
| pedido | 4/4 |
| politica | 4/5 |
| produto | 5/6 |
| reclamacao | 1/1 |

## Falhas

- `prod-04`: categoria: esperado 'Ukuleles', veio None
- `pol-02`: topico: esperado 'frete_entrega', veio 'loja'
- `ace-02`: faltou intenção ['acessorio']; intenção proibida ['buscar_produtos']
- `fora-03`: faltou intenção ['fora_de_escopo']; intenção proibida ['buscar_produtos']
