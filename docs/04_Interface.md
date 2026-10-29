# 4. Interface no PC – SOI Controller

Arquivo: [`interface/stm32_opt_inmmp_novo.py`](../interface/stm32_opt_inmmp_novo.py). Feito em PyQt/PySide + pyqtgraph. O lock-in é calculado em Python (numpy/scipy), no próprio arquivo.

## Instalação e execução

```powershell
pip install -r requirements.txt
python interface/stm32_opt_inmmp_novo.py
```

**Executável para Windows**. Cada [Release](https://github.com/mbelancon/SOI/releases) traz o executável pronto, sem precisar instalar Python:

- `SOI_Controller_vX.Y.Z.exe`: arquivo único. Basta baixar e abrir. A cada abertura ele se descompacta numa pasta temporária, por isso leva alguns segundos para aparecer.
- `SOI_Controller_vX.Y.Z_pasta.zip`: a mesma interface em pasta. Descompacte e abra `SOI_Controller.exe`. Abre mais rápido.

Nos dois casos a pasta `Medidas/` é criada ao lado do `.exe`. Como o executável não é assinado, o Windows SmartScreen pode avisar na primeira vez: clique em "Mais informações" e "Executar assim mesmo".

**Processador necessário.** O executável e as versões atuais do numpy (2.4 ou mais nova) e do Qt (6.10 ou mais nova) exigem um processador x86-64 com as instruções SSSE3, SSE4.1, SSE4.2 e POPCNT, o nível chamado x86-64-v2. Qualquer Intel desde 2009 (Core i3/i5/i7 de 1ª geração em diante) ou AMD desde 2011 (FX/Bulldozer, Ryzen) atende. Em processadores mais antigos, como AMD Phenom II/Athlon II e Intel Core 2, o programa não abre e mostra:

```
ImportError: DLL load failed while importing _multiarray_umath: Uma rotina de inicialização da biblioteca de vínculo dinâmico (DLL) falhou.
```

Instalar driver ou o Visual C++ não resolve, porque faltam instruções no próprio processador. Nesses PCs é possível rodar com bibliotecas mais antigas (por exemplo, numpy 2.3 e PyQt5 5.15), mas num teste com um Phenom II o computador não deu conta da taxa de dados do INMP441, e o sinal ficou cortado. Use um PC mais novo.

O executável é gerado pelo GitHub Actions ([`.github/workflows/executavel-windows.yml`](../.github/workflows/executavel-windows.yml)) sempre que uma Release é publicada, e também pode ser gerado à mão na aba Actions. Para gerar localmente no Windows, num venv limpo:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r packaging/requirements-build.txt
.venv\Scripts\pyinstaller packaging/soi_controller.spec             # arquivo único em dist/
.venv\Scripts\pyinstaller packaging/soi_controller.spec -- --onedir # pasta em dist/SOI_Controller/
```

O spec ([`packaging/soi_controller.spec`](../packaging/soi_controller.spec)) deixa de fora os módulos não usados do Qt, as traduções e o OpenGL por software. Não usa o [UPX](https://upx.github.io/): com ele o executável fica uns 14 MB menor, mas o Controle Inteligente de Aplicativos do Windows 11 bloqueia as DLLs comprimidas e a interface não abre (`-- --upx` liga, para testes).

## Conexão com o STM32

- A porta é **detectada sozinha**. A ordem é: a variável de ambiente `TL_ARDUINO_PORT` (ex.: `COM7`), se existir; depois um dispositivo USB com VID `0x0483` (STM32); depois outras placas Arduino conhecidas; por fim, a única porta USB presente.
- Se a conexão cair, a interface **tenta reconectar a cada 3 s** e reenvia a frequência e o PWM atuais.
- A leitura serial roda numa thread separada: nenhum byte se perde se a interface atrasar.
- **Verificação da modulação:** o PLL do OPT101 trava nas bordas reais do laser. Se ele ficar destravado por mais de max(5 s, 5 períodos), o STM32 está modulando em outra frequência: o `F` se perdeu, ou a placa reiniciou no padrão de 5 Hz. Nesse caso a interface reenvia a frequência sozinha e avisa na barra de status. Isso protege principalmente o lock-in do INMP441, que não tem PLL e depende de a frequência do STM32 ser a mesma do campo. Enquanto o PLL está destravado, o status da aba OPT101 mostra **"PLL destravado"**.
- **Sem STM32**, aparece a opção **"Simular amostragem"**, que gera sinais simulados do OPT101 e do INMP441 para testar a interface.
- As preferências (campos, opções, tamanho da janela, aba ativa) ficam salvas ao fechar, no registro do Windows (`HKCU\Software\LCTM\SOI Controller`). Não são salvas se uma varredura estiver em andamento.

## Barra de excitação (comum às abas)

| Controle | Faixa | Função |
|---|---|---|
| Freq (Hz) | 0 – 5000 | Frequência da modulação do laser (0 = contínuo). Também atualiza os cortes automáticos dos filtros. |
| PWM (%) | 0 – 100 | Potência do laser |
| **Amostra** | texto | Prefixo de todos os arquivos salvos em `Medidas/`. Caracteres inválidos em nomes de arquivo viram `_`. Vazio = sem prefixo. Fica salvo entre sessões. |
| Calibração + Usar | lista | Calibração do microfone aplicada na varredura em frequência do Modo Duplo. Lista as calibrações da pasta `Medidas/` da mais recente para a mais antiga (pela data no nome), sem os trechos `CAL_` e `microfone_`; o nome completo aparece na dica. A lista é relida ao abrir. Ao iniciar, a mais recente vem selecionada e com **Usar** marcado. |
| Finalizar experimento | botão | Compacta em `Medidas/<amostra>_<data>.zip` todos os arquivos salvos na sessão (desde que a interface abriu ou desde o último clique) e a calibração em uso (CSV e PNG). Os originais continuam na pasta. Durante uma varredura, ele pede para terminá-la ou cancelá-la antes. |

## Aba OPT101

**Barra de status:** estado do sinal (*Sinal OK*, *Sinal baixo* com nível médio < 5 % do ADC, ou *SATURAÇÃO DO ADC*), o **%ADC** de pico (verde < 50 %, laranja até 70 %, vermelho acima) e a **frequência real medida pelo PLL**.

**Osciloscópio:** sinal bruto do ADC (0–16 380) e a referência do laser (verde tracejado), em tempo real.
- *Janela (s)*: de 0,005 a 30 s. Acima de 50 Hz a janela fica limitada a 50 ciclos ("Visualização reduzida").
- *Filtro 60 Hz*: notches em 60 Hz e harmônicos até 1,5 kHz (largura de 2 Hz). Os notches a menos de 5 Hz da modulação são omitidos.

**Gráfico inferior, dois modos:**

1. **Lock-In:** magnitude (azul) e fase (vermelho) no tempo. São 50 pontos/s, e o gráfico mostra os últimos 200 (4 s).
   - *Passa-Baixas* / *Passa-Altas* (Hz): os cortes são automáticos ao mudar a frequência (LP = 5 % de f, limitado a 0,08–0,5 Hz; HP = 2 % de f, limitado a 0,01–0,05 Hz) e podem ser editados à mão. O rótulo τ mostra a constante de tempo de cada polo.
2. **Valor Médio:** forma de onda média do ADC sobre N pulsos (1–1000), sincronizada na borda de subida do laser.
   - ◀ / ▶ ajustam o pré-trigger em passos de 10 ms.
   - **Análise da curva** (com o gráfico pausado): ajuste de **1 ou 2 exponenciais** `y = y∞ + A1·e^(−t/τ1) [+ A2·e^(−t/τ2)]` no trecho *On* ou *Off*. O intervalo é escolhido com duas linhas verdes arrastáveis. **Fit** desenha o modelo com os parâmetros digitados; **Otimizar** faz mínimos quadrados a partir deles e mostra o R².

*Pausa* congela o gráfico. **Salvar** grava CSV + PNG do gráfico inferior em `Medidas/`.

**FFT** (caixa ao lado de *Salvar*): espectro do sinal bruto do ADC, numa coluna à direita, em dBFS.
- Padrão: zoom em torno da referência, com FFT de 4 s de histórico (resolução ≈ 0,25 Hz).
- *Espectro completo*: de 0 a 6,25 kHz, FFT de 4096 pontos (≈ 3,1 Hz).
- *Fit*: ajusta a amplitude do pico na frequência real da modulação com a forma exata de uma senoide na janela Hann e mostra A (em FS, dBFS e contagens do ADC), o SNR pico/piso e a resolução. Se o pico estiver abaixo do limiar de sinal baixo, o gráfico avisa em vez de mostrar o fit.

![Aba OPT101 com a FFT do ADC e o painel de varreduras aberto (modo simulado)](imagens/interface_opt101.png)

**Varreduras (botão *Varreduras ▸*, só no modo Lock-In):**
- *Varredura em frequência*: início, fim e passo (0,1–5000 Hz).
- *Varredura em PWM*: início, fim e passo (0–100 %), na frequência atual.
- Em cada ponto a varredura **espera max(1 s, 9τ) + 0,3 s** para o filtro estabilizar e depois **mede por max(1 s, 4τ)**. Mostra o tempo estimado, o tempo restante e uma barra de progresso. O mesmo botão cancela.
- Ao terminar ou ser cancelada, uma varredura em frequência (OPT101, INMP441 ou Modo Duplo) volta à frequência de antes, reenviando `F` ao STM32, e aos cortes de filtro de antes, inclusive os ajustados à mão.
- No fim abre uma janela com magnitude ± desvio-padrão e fase × variável. Os eixos podem ir para escala log, com **fit de lei de potência (A·xⁿ)** ou **linear**.

## Aba INMP441

Lock-in do microfone, com filtros **independentes** dos do OPT101. A referência é numérica: a fase vem do número de sequência da amostra I2S e do marcador de modulação, sem PLL.

**Status:** taxa de amostras recebidas e o aviso **"SINAL BAIXO"** quando o SNR cai abaixo do limiar.

**Exibição:**
- Gráficos ligáveis: **Lock-In**, **Ruído/SNR** e **FFT**.
- **R/θ ↔ X/Y**: magnitude e fase, ou componentes em fase e em quadratura.
- **Auto-fase**: zera a fase média do último 1 s (o sinal vai todo para X). *Offset (°)*: correção manual.
- **Varreduras ▸**: mostra as varreduras em frequência e PWM do INMP441, que funcionam como as do OPT101.

**Lock-in:** Passa-Baixas, Passa-Altas, Filtro 60 Hz e *Janela (s)* (1–60 s exibidos). São 20 pontos/s (blocos de 1600 amostras).

**Ruído/SNR:** média e desvio-padrão da saída do lock-in numa janela móvel (a mesma janela do gráfico, até 30 s). O SNR é mostrado em dB. O *Alerta SNR < (dB)* tem padrão de 10 dB (sinal ≈ 3× o ruído). Use uma janela de pelo menos 10τ.

**FFT:**
- Padrão: zoom em torno da referência, com FFT de 4 s de histórico (resolução ≈ 0,25 Hz).
- *Espectro completo*: de 0 a 16 kHz, FFT de 4096 pontos (≈ 7,8 Hz), em dBFS.
- *Fit*: ajusta o pico perto da referência com a forma exata de uma senoide na janela Hann. Corrige a frequência e a amplitude mesmo quando o tom cai entre dois bins.

## Aba Modo Duplo

Mede os dois lock-ins **no mesmo passo**. O R do OPT101 (proporcional à intensidade óptica) serve de referência de potência para o R do INMP441 (sinal fotoacústico).

**Topo da aba:**
- **Executar varreduras ▸** mostra os quadros das varreduras. Ele começa fechado e o estado fica salvo entre sessões. O botão Parâmetros de calibração abre esse painel automaticamente.
- **Abrir varredura…** carrega qualquer CSV do Modo Duplo da pasta Medidas, em frequência ou casada em PWM, inclusive os de formato antigo. A varredura aparece como se tivesse acabado de rodar: dá para aplicar calibração, ajustar modelos, excluir pontos, usar Fitar padrão e gerar calibração.
- **Salvar de novo** com uma varredura aberta grava `<nome original>_editado_<hora>.csv`, registrando o arquivo de origem no cabeçalho.
- **Limitação:** a varredura aberta não traz os cortes de filtro usados em cada ponto, então o diagnóstico do τ do canal óptico não aparece.

**Medida** (cada varredura tem a sua, no próprio quadro, então o botão de calibração não altera a varredura em PWM):
- *Média no tempo (τ atual)*: usa os filtros atuais (na varredura em frequência, os cortes automáticos de cada ponto). Espera 9τ do lock-in mais lento e faz a média por 4τ.
- *Integração longa (τ da varredura)*: usa temporariamente o τ escolhido nos dois passa-baixas (os valores são restaurados no fim). Espera 9τ e faz a média por 1τ. Dá menos ruído por ponto, mas a varredura demora mais.

**Varreduras:**
1. **Casada em PWM**: gráfico INMP441 R × OPT101 R com **ajuste linear** e gráfico OPT101 R × PWM. Verifica a linearidade do sinal fotoacústico com a potência.
2. **Em frequência (normalizada pelo OPT101)**: espaçamento **logarítmico** (N pontos) ou **linear** (passo). Os gráficos mostram **S = R_INMP441 / R_OPT101** e **Δφ = φ_INMP441 − φ_OPT101** (desenrolada).

**Excluir pontos do ajuste:** clique num ponto do gráfico da esquerda (magnitude) para tirá-lo do ajuste. Ele fica vazado e cinza, e o ajuste é refeito na hora; clique de novo para incluí-lo, ou use **Incluir todos**. Quando há pontos sobrepostos, vale o mais próximo do cursor. Os pontos excluídos aparecem listados abaixo do gráfico, no cabeçalho do CSV do Modo Duplo (os dados continuam completos) e, na calibração, com `Valido = 0` e uma linha no cabeçalho. Uma varredura nova começa sem exclusões.

**Salvar de novo:** o CSV e o PNG do Modo Duplo são gravados automaticamente no fim da varredura. Depois de excluir pontos, ligar o "Fitar padrão" ou trocar a calibração, use **Salvar de novo** para gravar arquivos novos com sufixo `_editado`. O cabeçalho deles traz o ajuste, as exclusões e a calibração atuais, mais o nome do arquivo original, que não é alterado.

**Ajuste com modelos** (painel recolhível, só na varredura em frequência). Ajusta a magnitude, a fase ou as duas com modelos de célula aberta (luz por fora, microfone atrás da amostra). Com x = √(f/f₁) e f₁ = α/(πL²):

| Modelo | S(f) ∝ | Resultado |
|---|---|---|
| Lei de potência | f⁻ⁿ (fase constante; só magnitude) | n |
| Duas leis de potência (com quebra) | f⁻ⁿ¹ abaixo de fb, f⁻ⁿ² acima (contínuas; só magnitude) | n₁, n₂, fb (linha pontilhada no gráfico) |
| Difusão térmica (placa, detecção traseira) | f⁻⁰·⁵ / [σL·sinh(σL)], σL = (1+i)x | f₁ |
| Flexão termoelástica (Perondi–Miranda) | f⁻¹·[(1 − 1/x) + i/x] | f₁ |

- **Constantes livres:** a amplitude e a fase de cada modelo são livres. Com a calibração aplicada (**Usar**), os dados já estão referidos à folha fina de alumínio (∝ f⁻¹·⁵), então o modelo descreve só a amostra. Sem calibração, o painel avisa que magnitude e fase incluem a resposta do microfone/célula e o atraso do sistema.
- **Espessura:** com a **Espessura L** informada, o painel calcula a difusividade térmica **α = π·f₁·L²**. A incerteza mostrada não inclui a de L, que entra em dobro.
- **Faixa:** a **Faixa: de … a … Hz** limita o ajuste à região onde o modelo vale. Os pontos excluídos com clique também ficam fora. A curva verde tracejada é desenhada só na faixa ajustada.
- **Arquivos:** o resultado vai para o cabeçalho do CSV do Modo Duplo (use **Salvar de novo** depois de ajustar).
- **Ti de 23/10:** a flexão ajustada pela fase deu f₁ ≈ 22–23 Hz (resíduo de ~11°). A difusão pura não descreve esse Ti.

**Calibração do microfone (padrão de alumínio), em 4 passos.** As ferramentas ficam no painel recolhível **Calibração de papel alumínio ▸**, fechado por padrão. O nome lembra que o modelo do ajuste (folha de alumínio fina e livre) só vale com esse padrão: com outras amostras ele dá parâmetros sem sentido físico. Por isso, com o painel fechado, "Fitar padrão" não é aplicado.
1. Com a folha de alumínio na célula, clique em **Parâmetros de calibração**. O botão preenche a varredura em frequência com os valores recomendados (definidos em `CAL_SWEEP_*` no topo do script):
   - 5 a 2440 Hz, 35 pontos logarítmicos;
   - integração longa com τ = 2 s (≈ 12 min);
   - PWM de 100 %;
   - Filtro 60 Hz desligado nos dois lock-ins e **Usar** da calibração desmarcado (a calibração nova precisa dos dados brutos).

   Os campos continuam editáveis. Confira o %ADC do OPT101 e rode a varredura em frequência. Esses valores mantêm todos os pontos a ≥ 4 Hz de qualquer múltiplo de 60 Hz e longe das frequências em que o período é um número inteiro de amostras do OPT101 (ex.: 2500 Hz). Nessas frequências, a grade de 80 µs deixa um erro de até ~2 % no R.
2. Marque **Fitar padrão**. O modelo é `S(f) = A·f⁻ⁿ·H(f)`, com H um passa-altas de 1ª ordem de corte fc (microfone/célula), e `Δφ(f) = φ0 + atan(fc/f) − 360°·f·td`. *Incluir fase* usa também a fase. Pontos com SNR baixo ou resíduo > 3σ ficam marcados com ✕ vermelho.

   **τ efetivo do canal óptico (diagnóstico):** toda varredura em frequência também ajusta `φ(f) = φ0 + digital(f) − atan(2π·f·τ)` à fase do OPT101. `digital(f)` é o atraso conhecido do firmware (`OPT_REF_DELAY` ≈ 36,7 µs) mais o passa-altas do DC e os notches. Esse τ efetivo inclui o sensor e o driver/laser. A linha de resultado também mostra o τ pela queda de amplitude. Se os dois não concordarem, há um atraso puro antes do sensor. Na montagem de 23/10/2026, o τ efetivo foi de ~70 µs, dos quais só ~8 µs vinham do OPT101. O atraso do driver/laser é comum ao microfone e se cancela em Δφ, por isso **não** é corrigido.

   **τ do sensor (correção):** com **Descontar τ do sensor** marcado e um valor no campo, o OPT101 é corrigido pelo polo do sensor antes de calcular S e Δφ. A fase recebe `+ atan(2π·f·τ)` e a amplitude é multiplicada por `√(1 + (2π·f·τ)²)`. Assim, a calibração deixa de depender do resistor de realimentação. O valor vale para o resistor montado agora e fica salvo entre sessões. Ao trocar o resistor, troque o valor. 0 = sem correção.
   - **Medir…** compara a varredura em frequência atual com outra já salva (`DUPLO_freq_*.csv`). As duas precisam ter a mesma luz (mesmo PWM e alinhamento) e resistores que mudem o ganho pelo menos 1,3×.
   - Na diferença de fase, a cadeia digital e o driver/laser se cancelam. O polo do OPT101 é proporcional a R_eq, e a razão de R_eq vem da razão dos R. O campo é preenchido com o τ da varredura atual.
   - Para resolver o τ, as varreduras precisam ir até 1–2,4 kHz.
3. **Gerar calibração do microfone**: calcula a sensibilidade relativa `M(f) = S(f)·f^1,5` (a folha fina livre tem S ∝ f⁻¹·⁵) e a fase do sistema. Também procura a **faixa plana** dentro de ±tol dB (padrão de ±1 dB). Salva `CAL_microfone_*.csv` e `.png`. O cabeçalho registra os τ e a linha `OPT101_tau_sensor_s` (0 = sem correção).
   - Se uma calibração for aplicada a uma varredura com a escolha oposta de correção, a interface avisa.
   - Calibrações **sem** essa linha recebem o aviso "Calibração antiga": foram feitas com o firmware anterior ao marcador de modulação corrigido (23/10/2026 14:43, ver [03_Firmware_STM32.md](03_Firmware_STM32.md)) ou com a correção pelo τ efetivo. Nesses casos a fase do sistema não é comparável (td ~100 µs maior). Gere uma calibração nova.
4. A calibração nova já aparece selecionada em **Calibração:**, na linha superior. Marque **Usar**: as varreduras em frequência do Modo Duplo passam a ser corrigidas por ela, e os pontos fora da faixa calibrada ficam ocultos. O CSV exportado registra no cabeçalho o nome do arquivo de calibração usado. Os dados gravados continuam brutos.

## Arquivos gerados (`Medidas/`)

Todos os arquivos são CSV em UTF-8, com cabeçalho de comentários (`#`) que traz os parâmetros. Cada CSV tem um PNG com o mesmo nome.

| Origem | Nome do arquivo | Colunas |
|---|---|---|
| Salvar (Lock-In) | `LockIn_<f>Hz_<data>` | Tempo_s, Magnitude, Fase_Graus |
| Salvar (Valor Médio) | `ValorMedio_<f>Hz_<data>` | Tempo_s, ADC_Medio [, Fit_Exp] |
| Varredura F | `OPT101_F_varredura_f<ini>_f<fim>_<passo>_<data>` (ou `INMP441_…`) | Frequencia_Hz, Magnitude_Media, Magnitude_DesvioPadrao, Fase_Media_Graus, Fase_DesvioPadrao_Graus, DC_Offset_Medio |
| Varredura P | `OPT101_P_varredura_p<ini>_p<fim>_<passo>_f<f>Hz_<data>` (ou `INMP441_…`) | PWM_Pct, (mesmas colunas) |
| Modo Duplo, PWM | `DUPLO_casada_pwm<ini>_<fim>_f<f>Hz_<data>` | PWM_Pct, OPT101_R, OPT101_R_DP, INMP441_R, INMP441_R_DP, INMP441_Fase_Graus, INMP441_Fase_DP, OPT101_Fase_Graus, OPT101_Fase_DP |
| Modo Duplo, freq. | `DUPLO_freq_<ini>_<fim>Hz_pwm<p>_<data>` | Frequencia_Hz, (mesmas colunas) |
| Calibração | `CAL_[<amostra>_]microfone_<ini>_<fim>Hz_<data>` | Frequencia_Hz, Sensibilidade_Rel, Sensibilidade_Rel_DP, Sensibilidade_Fit, Fase_Sistema_Graus, Fase_DP, Valido, Faixa_Plana |

Com o campo **Amostra** preenchido, todos os nomes começam com `<amostra>_` (ex.: `Grafite_OPT101_F_varredura_…`). A exceção é a calibração, que começa com `CAL_` e só depois traz o nome da amostra: `CAL_<amostra>_microfone_…` (sem amostra: `CAL_microfone_…`). "Usar última calibração" pega o arquivo `CAL_*microfone_*.csv` mais recente, com qualquer nome de amostra. O formato de `<data>` é `AAAAMMDD_HHMMSS`. Os dados do Modo Duplo são sempre gravados **brutos**, mesmo com a calibração aplicada no gráfico.

## Especificações resumidas

| Item | OPT101 | INMP441 |
|---|---|---|
| Taxa de amostragem | 12 500 S/s | 31 994 S/s (nominal 32 k) |
| Resolução | 14 bits (0–16 380) | 24 bits com sinal |
| Banda útil | 0 – 6,25 kHz | 0 – 16 kHz |
| Referência do lock-in | PLL por software, travado nas bordas do bit REF | Numérica (sequência I2S + marcador de partida) |
| Demodulação | Quadratura, passa-baixas de 2 polos em cascata, remoção de DC com passa-altas de 1 polo | idem |
| Saída do lock-in | 50 pontos/s | 20 pontos/s |
| Filtro de rede | Notches em 60 Hz e harmônicos até 1,5 kHz (opcional) | idem |
| Modulação | 0,1 – 5000 Hz (ou contínuo) | — |
| Potência | PWM de 5 kHz, 0 – 100 % em passos de 0,1 % | — |
| Atualização da tela | 25 quadros/s | — |

**Correção da média do firmware (OPT101):** cada amostra óptica é a média de 16 conversões do ADC numa janela de 80 µs (= 1/FS). Essa média atenua a fundamental por sinc(f/FS): −1 % em 1 kHz, −4 % em 2 kHz e −9 % em 3 kHz. A magnitude do lock-in do OPT101 já sai dividida por esse fator, então os valores de R gravados estão corrigidos. A fase não precisa de correção: a referência (bit REF) é tirada da mesma janela.

**Detalhes do PLL (OPT101):** o PLL trava quando o período entre bordas está dentro de ±(2 amostras + 0,1 %) do nominal. Os ganhos são Kp = 0,05 e Ki = Kp²/4, e a frequência fica limitada a ±5 % da nominal. O PLL destrava se o erro médio de fase passar de 1,1 rad ou se ficar sem bordas por 10 s.
