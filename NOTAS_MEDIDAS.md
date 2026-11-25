# NOTAS DE MEDIDAS — SOI

Descobertas das campanhas e notas de calibração/ressonância, tiradas do CONTEXTO.md em 20/11 para deixá-lo curto.
Não é carregado em toda sessão: ler quando o trabalho for de medida, análise ou calibração.

## Campanha de deriva (16–17/11, alumínio) — descobertas
Dados + relatório: `interface\Medidas\Campanha_deriva_20261116\Campanha_deriva_20261116.zip`
(relatório: Claude Doc "Campanha de deriva 16-17/11").
- Abaixo de ~30–40 Hz domina ruído acústico do ambiente, aditivo e independente do laser (fundo a 10 Hz ≈ 1/3 do
  sinal no Al; a ≥ 100 Hz, 1–5 %). Baixar o PWM só piora o SNR: medir a 100 %. Inox dá mais sinal (melhor no grave).
- Deriva = aquecimento depois que o laser liga: S −14 % com T ≈ 4,4 min a 10 Hz (OPT101 −4 %, T ≈ 1 min); depois
  estável por 1 h. Pouco efeito a 300–1000 Hz. Daí o "Aguardar warm-up" (300 s).
- Ruído branco até ~4 min de média (Allan 12 % em 5 s → 1,7 % em 4 min a 10 Hz; piso ~1,4 %).
- Varreduras a 1/2/4 %: concordam em ~2 % acima de 40 Hz; 5–11 % abaixo. A flutuação da janela não é a incerteza
  do ponto (subestima no grave, superestima no agudo). Proposta de regra com blocos e incerteza u: no relatório,
  ainda não implementada.
- 300 Hz (harmônico de 60 Hz) tem fundo no OPT101: evitar múltiplos de 60 Hz em frequência fixa.

## Campanhas de ruído e aquecimento (18/11) — descobertas
Relatório: Claude Doc "SOI noise and drift study (Nov 2026)". Peças de Al 30×20×18 mm e Al pequena.
- Deriva de S ao ligar o laser é maior em baixa f e na peça menor (que aquece ~2× mais rápido). O efeito direto
  da temperatura do gás (1/T0) explica só ~0,3–0,5 %. Vazamento descartado (a fase quase não muda); ver 19/11.
- OPT101: queda rápida de ~4 % ao ligar é potência real do laser. Oscilação lenta de ~1 % (período ~36 min):
  provavelmente o ar-condicionado (liga 8h–18h; ver 19/11). Speckle no espelho que alimenta o OPT101 ainda pode
  causar deriva lenta (solução: lamínula como divisor de feixe + difusor; diagnóstico com webcam).
- Termopar: o salto ao ligar o laser é interferência do PWM pelo contato com o Al (teflon reduz).
- Noite 18→19/11 (até ~9h40, ar-condicionado desligado): fundo com PWM 0, varreduras crescente + 12 frequências
  embaralhadas e 90 min a 487 Hz desde frio.

## Campanhas de 19/11 — descobertas
Relatório: Claude Doc "SOI noise and drift study (Nov 2026)" (tabela de hipóteses no início).
- A deriva de S ao ligar o laser NÃO segue a temperatura média da peça: a de 120 mm aquece 5× menos que o disco e
  perde só ~2× menos sinal (37 Hz: −10 %, τ ≈ 95 s). Hipótese: aquecimento local sob o feixe (superfície/gás).
  Descartados: potência do laser, vazamento, 1/T do gás. S_120/S_disco = 5,5 a 40 Hz e 2,35 acima de 800 Hz.
- Oscilação de ~36 min do OPT101 sumiu com o ar-condicionado desligado: provavelmente o ar. Deriva noturna de
  ~2,6 % está na referência OPT101 (espelho/speckle), não na amostra.
- Ordem das frequências não importa após ~11 min de laser; a varredura crescente fica 3–4 % alta em 80–130 Hz
  por aquecimento no início.
- τ curto não enviesa; de dia τ = 1 s espalha 2–4× menos no grave. Fundo diurno 3–5× maior que o noturno.
- Descarte por vizinhas não ajudou à noite; decidir depois dos testes diurnos.
- Varredura recomendada: τ = 1 s, 3 repetições, mediana, warm-up 10–15 min, sem múltiplos de 60 Hz e sem a série
  da ventoinha, grave (< 100 Hz) à noite.

## INMP441 em baixa frequência
- Datasheet: especificado para f > 60 Hz. Mede abaixo, mas com mais ruído próprio, somado ao ruído da sala.
- Ruído da sala varia com o horário (aulas até 23h; depois, tráfego na rodovia em frente ao laboratório).
- Dois microfones (em breve): um segundo INMP441 de referência (fora da célula, ou numa célula cega) permite
  subtrair o ruído ambiente coerente; dois na célula, em média, reduzem o ruído próprio ~√2. Os dois cabem no
  mesmo barramento I2S (pino L/R: canal esquerdo e direito); o firmware passa a ler os dois canais.

## SNR e incerteza por ponto (análise de 17/11, `dados_artigo/ANALISE_20261117.md`)
- Ruído do INMP441 ~10⁻⁵ FS em todas as amostras; o que muda é o sinal (Al/Inox ~10⁻³ FS, acrílico/OPC ~10⁻⁴).
- Erro do ponto (f < 500 Hz): < 15 dB ~44 %, 15–25 dB 10–25 %, ≥ 25 dB ≲ 10 % (piso ~7 %, ruído acústico/deriva).
  Cores do SNR na interface: verde ≥ 25, amarelo 15–25, vermelho < 15 dB. Reavaliar com τ maior (τ = 2 s dá +3 dB).

## Calibração (notas)
- Calibração da câmara por duas amostras grossas (Al + Inox 316L; latão/grafite como alternativas): razão S_A/S_B
  plana (±1 dB, ±10°, ≥ 1 década) verifica; H = média geométrica de S·f das duas; f0 iguais (±3 %). Modo OPC
  mantido, com duas folhas finas (nunca folha de inox). A calibração da câmara não serve para o OPC.
- O f⁻² visto no Inox/Al em 13/11 vinha da calibração com negro de fumo (o negro de fumo bruto sobe ~f^+0,9),
  não da amostra. Não usar aquela calibração.
- Inox lado B dá 0,57× o lado A e só concorda com o Al até ~130 Hz: usar sempre a mesma face.

## Ressonância da célula (notas, 16/11)
- f0 salta entre estados por montagem: ~1,05–1,12 kHz (todas de 13/11, latão e Ni+filme de 16/11),
  ~1,53–1,55 kHz (Al e Inox de 16/11 de manhã) e ~1,79 kHz (Ni 10h11). Mesmas peças mudam de estado entre dias:
  é montagem/geometria acústica, não material nem temperatura; não tem assinatura de vazamento.
- A CAL Al-Inox de 16/11 09h16 foi feita no estado alto e não vale acima de ~500 Hz para medidas no estado baixo.
  Conferir f0 antes de aplicar uma calibração (a interface avisa "Ressonância deslocada"). Gráfico: `analises/ressonancia_estados_20261116.png` (pasta do projeto).
