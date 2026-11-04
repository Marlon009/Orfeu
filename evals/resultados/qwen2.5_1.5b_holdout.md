# Bateria do intérprete — `qwen2.5:1.5b` — holdout

03/11/2026 22:41 · temperatura 0

**Acerto: 8/11 (73%)** · tempo médio 4 s · campos inventados descartados pela conferência: 5

| Grupo | Acerto |
|---|---|
| acessorio | 1/1 |
| fora_de_escopo | 1/1 |
| multiplo | 0/1 |
| nao_recusar | 1/1 |
| pedido | 2/2 |
| politica | 1/2 |
| produto | 2/2 |
| reclamacao | 0/1 |

## Falhas

- `pol-06`: faltou intenção ['consultar_politica']; topico: esperado 'privacidade', veio None
- `rec-02`: faltou intenção ['registrar_reclamacao']
- `multi-02`: topico: esperado 'frete_entrega', veio 'loja'
