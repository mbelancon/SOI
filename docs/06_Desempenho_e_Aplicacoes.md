# 6. Desempenho e aplicações

Este guia resume o que o sistema consegue medir no tempo com o canal óptico (OPT101) e avalia, com números, três aplicações: **lente térmica**, **espelho térmico** e **decaimento de luminescência**. Os valores de aquisição vêm do firmware ([`main.cpp`](../firmware/src/main.cpp)) e da interface ([`stm32_opt_inmmp_novo.py`](../interface/stm32_opt_inmmp_novo.py)). Os do OPT101 vêm do datasheet da Texas Instruments, para o resistor interno de 1 MΩ.

> As estimativas de aplicação abaixo são de projeto, não medidas de validação. Antes de publicar resultados com elas, confira a resposta do sistema com uma amostra de tempo conhecido.

## Cadeia de aquisição óptica

| Etapa | Valor | Efeito no tempo |
|---|---|---|
| ADC do STM32 (PA0) | 12 bits, **200 kS/s**, disparado pelo TIM3; amostragem de 84 ciclos a 21 MHz (4 µs) | Instante de cada amostra fixo pelo cristal, sem jitter |
| Sobreamostragem | 16 amostras somadas → **12,5 kS/s**, 14 bits efetivos (0 a 16 380) | Cada ponto é a média de **80 µs** (filtro boxcar) |
| Referência do laser | Estado do PB0 lido pelo DMA no mesmo gatilho do ADC; maioria das 16 amostras por ponto | A borda do laser é conhecida com passo de **80 µs** |
| USB CDC | 62,5 kB/s ópticos + ≈97,5 kB/s de áudio ≈ **160 kB/s** | Limita a taxa atual |
| OPT101, 1 MΩ interno | Banda de **14 kHz**, tempo de subida (10–90 %) ≈ **28 µs**, 0,45 A/W em 650 nm | Suaviza bordas mais rápidas que ~30 µs |
| Modulação do laser (TIM4) | Onda quadrada de 50 %, **0,1 a 5000 Hz**, resolução de 95 ns | Define a janela de cada pulso |
| PWM do laser (TIM1, PA8) | Portadora de **5 kHz** (período de 200 µs) | Abaixo de 100 % a luz "ligada" é picotada a 5 kHz |

**Escala de intensidade.** Com o resistor de 1 MΩ, uma contagem (≈ 0,20 mV) equivale a ≈ 0,45 nW em 650 nm, e o fundo de escala (3,3 V) a ≈ 7 µW. A responsividade cai nas pontas da faixa do silício: o OPT101 responde de ~300 a 1100 nm, com pouco sinal acima de ~1000 nm.

## Medidas no tempo: modo Valor Médio

Na aba OPT101, o modo **Valor Médio** promedia a forma de onda do ADC sobre N pulsos (1 a 1000), alinhada na borda de subida do laser, com pré-trigger ajustável. A **Análise da curva** ajusta 1 ou 2 exponenciais no trecho *On* ou *Off* e mostra τ e R².

**Resolução temporal efetiva.** Três efeitos se somam:

1. cada ponto é uma média de 80 µs;
2. a borda do laser só é localizada com passo de 80 µs. Se o período da modulação não for múltiplo exato de 80 µs, o alinhamento varia de pulso para pulso e a média alarga a borda em até 80 µs (≈ 23 µs rms);
3. o tempo de subida do OPT101, ≈ 28 µs.

O resultado é uma resposta do sistema com tempo de subida da ordem de **0,1 ms**. Na prática:

| Constante de tempo τ | Situação |
|---|---|
| τ ≥ 0,5 ms | Medida direta, com pelo menos ~6 pontos por τ e erro de forma pequeno |
| 0,1 ms ≤ τ < 0,5 ms | Possível, mas o ajuste precisa ignorar os primeiros ~0,1–0,2 ms após a borda ou convoluir o modelo com a resposta do sistema |
| τ < 0,1 ms | Fora do alcance do modo Valor Médio |

**O que limita o τ máximo.** O decaimento precisa terminar dentro do meio período em que o laser fica desligado (ou ligado): meio período ≥ 5τ, ou seja, f ≤ 1/(10τ). Com f mínima de 0,1 Hz, isso vai até τ ≈ 1 s.

**Cuidados.**
- Use **PWM = 100 %** em medidas no tempo. Com PWM menor, a portadora de 5 kHz aparece como ondulação de 200 µs sobre o sinal.
- Escolha f de modo que o período seja múltiplo de 80 µs (por exemplo 25 Hz = 40 ms, 50 Hz, 125 Hz), para que a borda caia sempre no mesmo ponto e a média não alargue a subida.
- O próprio laser e o driver têm tempo de subida. Meça a luz do laser direto no OPT101 para conhecer a resposta do conjunto antes de interpretar τ curtos.
- Cada média de N pulsos reduz o ruído aleatório por √N.

## Medidas em frequência: lock-in

O lock-in do OPT101 dá magnitude e fase na frequência fundamental da modulação, até **5 kHz**. Para um processo de primeira ordem, tg φ = 2πfτ, então a fase em função da frequência mede τ sem precisar resolver a borda no tempo. A interface já compensa o atraso digital da referência (constante `OPT_REF_DELAY`). Os atrasos que sobram (boxcar de 80 µs e banda do OPT101) são iguais para qualquer amostra e podem ser descontados medindo a luz do laser direto, sem amostra.

Em princípio, isso estende o alcance para **τ de algumas dezenas de µs** (a 5 kHz, τ = 30 µs dá φ ≈ 43°). Ainda não foi validado no sistema. A varredura em frequência da aba OPT101 já faz essa medida, e o ajuste de modelos do Modo Duplo serve de ponto de partida.

## Aplicações

### Lente térmica

O tempo característico é t_c = w²/(4D), em que w é o raio do feixe de excitação na amostra e D a difusividade térmica.

| Amostra | D (m²/s) | w = 50 µm | w = 100 µm | w = 200 µm |
|---|---|---|---|---|
| Água | 1,4 × 10⁻⁷ | 4,5 ms | 18 ms | 71 ms |
| Etanol | 0,9 × 10⁻⁷ | 7 ms | 28 ms | 110 ms |
| Polímeros (PMMA) | 1,1 × 10⁻⁷ | 6 ms | 23 ms | 90 ms |
| Vidros ópticos | 4–6 × 10⁻⁷ | 1–1,6 ms | 4–6 ms | 17–25 ms |

**Conclusão: dá para medir.** Todos esses valores estão bem acima de 0,5 ms. O transiente cabe numa modulação de 1 a 20 Hz e é resolvido com dezenas a centenas de pontos. Só feixes muito focados (w ≲ 25 µm) em vidros ficam perto do limite.

Montagem: o OPT101 mede a intensidade do feixe de prova no centro, atrás de um pinhole. O laser modulado pelo STM32 é o feixe de excitação. A análise do transiente (modelo de Shen) ainda não está na interface. Hoje é preciso exportar o CSV do Valor Médio e ajustar fora dela.

### Espelho térmico

O tempo característico tem a mesma forma, t_c = w²/(4D), mas D é o da amostra opaca ou absorvedora na superfície:

| Amostra | D (m²/s) | w = 100 µm | w = 500 µm |
|---|---|---|---|
| Vidros e polímeros | 1–6 × 10⁻⁷ | 4–25 ms | 0,1–0,6 s |
| Semicondutores (Si) | 8,8 × 10⁻⁵ | 28 µs | 0,7 ms |
| Metais (Al) | 9,7 × 10⁻⁵ | 26 µs | 0,6 ms |

**Conclusão: dá para medir em vidros, polímeros e materiais de baixa difusividade.** Em metais e semicondutores, t_c fica abaixo de 0,1 ms com feixes de ~100 µm. Nesses casos é preciso aumentar w (≳ 0,5 mm) ou usar o lock-in em frequência.

### Decaimento de luminescência

O OPT101 mede a luminescência da amostra, com um filtro que bloqueie a luz de excitação. O laser modulado excita, e o decaimento é observado no meio período desligado.

| Emissor | Tempo de vida típico | Comprimento de onda | Situação |
|---|---|---|---|
| Eu³⁺ (⁵D₀ → ⁷F₂) | 0,5–2 ms | ~612 nm | Mensurável |
| Tb³⁺ (⁵D₄) | 1–3 ms | ~545 nm | Mensurável |
| Cr³⁺ (rubi) | ~3 ms | 694 nm | Mensurável |
| Mn²⁺ | 1–20 ms | 500–650 nm | Mensurável |
| Yb³⁺ | 0,5–2 ms | ~980 nm | Mensurável, com sensibilidade reduzida |
| Nd³⁺ (⁴F₃/₂) | 0,1–0,4 ms | 880 / 1064 nm | No limite: tempo curto e pouca resposta do silício em 1064 nm |
| Er³⁺ (⁴I₁₃/₂) | 2–10 ms | ~1530 nm | **Não**: fora da faixa do silício (precisa de detector de InGaAs) |
| Corantes orgânicos, pontos quânticos, fluorescência em geral | ns a dezenas de ns | visível | **Não**: ~10⁴ vezes mais rápido que a resolução |

**Conclusão: o sistema serve para tempos de vida de ~0,2 ms a ~1 s.** É o caso dos íons terras-raras e dos metais de transição que emitem no visível e no infravermelho próximo até ~1000 nm. A fluorescência de nanossegundos e as emissões além de 1100 nm não estão ao alcance.

**Sinal.** A luminescência costuma ser fraca. Uma contagem do ADC corresponde a ≈ 0,45 nW em 650 nm. Sinais de poucos nW precisam de muitas médias (o ruído cai com √N) ou de um resistor de realimentação externo maior no OPT101, que aumenta o ganho mas reduz a banda.

## Como ir além

Estas mudanças não estão implementadas e exigem alterar o firmware e a interface juntos:

- **Taxa maior no canal óptico.** Com `OVS_BITS = 1` (4 amostras por ponto), a taxa sobe para 50 kS/s com 13 bits, e cada ponto passa a cobrir 20 µs. O fluxo óptico iria para ~250 kB/s, então seria preciso desligar o áudio num modo "só óptico" e conferir a banda real do USB CDC. A constante `FS` da interface teria de acompanhar.
- **Borda exata da referência.** Registrar o instante da borda do laser (como já é feito no marcador do INMP441) em vez de usar a maioria das 16 amostras eliminaria o alargamento de até 80 µs da média.
- **Detector mais rápido.** Abaixo de ~30 µs, o limite passa a ser o OPT101. Seria preciso um fotodiodo com amplificador de transimpedância mais rápido e um ADC externo.
