# Bateria do intérprete — `qwen2.5:1.5b` — dev

03/11/2026 22:33 · temperatura 0

**Acerto: 19/27 (70%)** · tempo médio 3 s · campos inventados descartados pela conferência: 6

| Grupo | Acerto |
|---|---|
| acessorio | 2/2 |
| conversa | 1/2 |
| fora_de_escopo | 1/3 |
| multiplo | 0/1 |
| nao_recusar | 1/3 |
| pedido | 4/4 |
| politica | 5/5 |
| produto | 4/6 |
| reclamacao | 1/1 |

## Falhas

- `prod-04`: faltou intenção ['buscar_produtos']; intenção proibida ['acessorio']; categoria: esperado 'Ukuleles', veio None
- `prod-06`: preco_max: esperado 9000, veio None
- `nrec-01`: faltou intenção ['buscar_produtos']; intenção proibida ['acessorio']
- `nrec-02`: faltou intenção ['buscar_produtos']; intenção proibida ['acessorio']; categoria: esperado 'Baterias e Percussão', veio None
- `fora-02`: faltou intenção ['fora_de_escopo']
- `fora-03`: faltou intenção ['fora_de_escopo']; intenção proibida ['buscar_produtos']
- `conv-02`: faltou intenção ['conversa']
- `multi-01`: faltou intenção ['consultar_politica']; topico: esperado 'pagamento', veio None
