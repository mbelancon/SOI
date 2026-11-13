# Roteiro de teste da 2.1.0 (referências de calibração)

Firmware: o mesmo da 2.0.0. Rode a interface com `python interface/soi_controller.py`.

1. **Abrir uma varredura antiga.** Modo Duplo → Abrir varredura… → um `*_DUPLO_freq_*.csv`. Abra "Calibração do microfone ▸" e marque "Fitar padrão". Troque a **Referência** e confira se o esquema, as dicas, a curva esperada e a **Célula** (linha superior) mudam juntos.
2. **Aviso de comportamento.** Com uma referência cujo n não bate com os dados, o texto vermelho deve aparecer com os números e as causas prováveis. Com "Fit até" abaixo da ressonância, o ajuste deve ignorar os pontos acima.
3. **Gerar calibração** (com "Usar" desmarcado). Se a verificação falhou, a interface pergunta antes. Confira na pasta Medidas o nome `CAL_…_microfone_<OPC|Camara>_…`, as linhas `Referencia`, `Celula`, `Verificada` no CSV e o título do PNG.
4. **Usar a calibração.** Marque "Usar": S corrigido deve seguir a curva da referência e a fase ficar constante. Troque a Célula para a outra configuração: deve aparecer o aviso de célula diferente. Uma calibração não verificada mostra ⚠ na lista e o aviso em vermelho.
5. **Calibração antiga.** Uma `CAL_microfone_*.csv` da 2.0.0 deve aparecer como `[OPC]`, sem ⚠ de verificação.
6. **Ressonância.** Desmarque "Usar", abra "Ajuste com modelos ▸", escolha "Ressonância da célula". Sem Faixa, o pico deve ser achado sozinho; com "Marcar pico (2 cliques)", dois cliques no gráfico da esquerda preenchem a Faixa. Confira f₀, Q, largura e ganho. Referência da célula nova (10/11, 35 pontos): f₀ ≈ 1,57 kHz, Q ≈ 6,5.
7. **Modelos de câmara.** "Câmara: amostra opaca" e "Câmara: transparente" devem desenhar a curva e mostrar os resíduos.
8. **Preferências.** Feche e reabra: referência, L, α, n, Fit até e Célula devem voltar como estavam.
