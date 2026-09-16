' 朴(2025c) 付録：モデル方程式（本体 p.82-89 の EViews 貼り付けより機械抽出）
' 式 169 本。PDF の折り返しを結合し、X( -1) → X(-1) の空白ゆれのみ正規化した。
' 係数・変数名は原文のまま。sfcsim.Model でのパース可否は paper/README.md を参照。

'Japan Stock-flow consistent macroeconometric model
'Park Seung-Joon, 2025/9/10
' **** SWITCH (NGBA_CB and RrB; Remove the apostrophes to have endogenous interest rate calculation) *************
'
'
'NGBA_CB  =  - ( NGBA_N  + NGBA_F  + NGBA_G  + NGBA_H  + NGBA_W )
RrB = RrB(-1) - 1e+7 * NGBA_SUM
'******** Macro-economic sub-model ************************************
' Finaicial income of each secotr
FINCOME_N = rH(-1) * NGSHA_N(-1) + rB(-1) * NGBA_N(-1) + rM(-1) * NDEPA_N(-1) + rL(-1) * NLBDA_N(-1) + chi * NEQUA_N(-1) + psi * NPENA_N(-1)
FINCOME_CB = rH(-1) * (NGSHA_CB(-1) - GOLD) + rB(-1) * NGBA_CB(-1) + rM(-1) * NDEPA_CB(-1) + rL(-1) * NLBDA_CB(-1) + chi * NEQUA_CB(-1) + psi * NPENA_CB(-1)
FINCOME_F = rH(-1) * NGSHA_F(-1) + rB(-1) * NGBA_F(-1) + rM(-1) * NDEPA_F(-1) + rL(-1) * NLBDA_F(-1) + chi * NEQUA_F(-1) + psi * NPENA_F(-1)
FINCOME_G = rH(-1) * NGSHA_G(-1) + rB(-1) * NGBA_G(-1) + rM(-1) * NDEPA_G(-1) + rL(-1) * NLBDA_G(-1) + chi * NEQUA_G(-1) + psi * NPENA_G(-1)
FINCOME_H = rH(-1) * NGSHA_H(-1) + rB(-1) * NGBA_H(-1) + rM(-1) * NDEPA_H(-1) + rL(-1) * NLBDA_H(-1) + chi * NEQUA_H(-1) + psi * NPENA_H(-1)
FINCOME_W = rH(-1) * NGSHA_W(-1) + rB(-1) * NGBA_W(-1) + rM(-1) * NDEPA_W(-1) + rL(-1) * NLBDA_W(-1) + chi * NEQUA_W(-1) + psi * NPENA_W(-1)
FINCOME_SUM = FINCOME_N + FINCOME_CB + FINCOME_F + FINCOME_G + FINCOME_H + FINCOME_W
'---- Non-financial corporations (N) --------------------------------------------------------------
' Wage bill is the product of wage rate and employment
WB_N = W * N_N
' Operating Surplus
B2 = 32528.9732858 + 0.965559285024 * YN - 1.17156961172 * WB_N - 300.063362365 * TIME
B2_N = sB2_N * B2
B2_F = sB2_F * B2
B2_G = sB2_G * B2
B2_H = sB2_H * B2
' Indirect Tax
LOG(TIN_N) = 3.94399710382 + 0.471460141874 * LOG(YN + MN - XN) + 0.0563215760515 * CONTAX + 0.129594502022 * DUM2014
' Direct Tax
TD_N = 3557.60325291 + 0.126762067821 * (YN - YN(-1)) + 0.820417728974 * TD_N(-1) - 4628.66784287 * DUM2009
' Gross saving
S_N = Yn - WB_N + (B2_N - B2) + FINCOME_N - TIN_N - TD_N + STR_N + epsilon_N
' Nominal capital stock
Kn_N = Kn_N(-1) + In_N - D_N + KCG_N
' Depreciation
D_N = - 5796.85244944 + 0.105309763467 * KN_N(-1)
' Real capital stock
Kr_N = Kn_N / Pi
' Real capital formation (Ir)
LOG(IR_N) = 2.38934707447 + 0.792491431252 * LOG(IR_N(-1)) + 1.76137417246 * @PCH(YR) - 0.911536913208 * RRL - 0.135830259778 * DUM2009
' Nominal capital formation
In_N = Ir_N * Pi
' Net Lending and net worth
NL_N = S_N - IN_N - NP_N + KTR_N + GAPNL_N
FNWL_N = ( - NNFWA_N)
NW_N = FNWL_N + Kn_N
FNWLr_N = FNWL_N / Pc
NWr_N = NW_N / Pc
'---- Bank of Japan, Central Bank (CB) ----------------------------------------------------------------------
' Net lending and net worth
NL_CB = FINCOME_CB + GAPNL_CB
FNWL_CB = ( -NNFWA_CB)
FNWLr_CB = FNWL_CB / Pc
'---- Financial sector, less Central Bank (F) ---------------------------------------------------------------
' Gross Saving
S_F = B2_F + FINCOME_F - T_F + STR_F - CPEN_F + epsilon_F
' Capital stock
Kn_F = Kn_F(-1) + In_F - D_F + KCG_F
' Net Lending and net worth
NL_F = S_F - In_F - NP_F + KTR_F + GAPNL_F
FNWL_F = ( -NNFWA_F)
NW_F = FNWL_F + Kn_F
FNWLr_F = FNWL_F / Pc
NWr_F = NW_F / Pc
'---- General Government (G) --------------------------------------------------------------------------------
' Tax Revenue, sum
T_G = (TIN_N + TD_N) + T_H + T_F + T_W
' Social transfer receipt (negative)
STR_G = - (STR_N + STR_H + STR_F + STR_W) + STR_GAP
' Gross saving
S_G = B2_G + FINCOME_G + T_G + STR_G - Gn + epsilon_G
' Capital stock
Kn_G = Kn_G(-1) + In_G - D_G + KCG_G
' Net Lending and net worth
NL_G = S_G - In_G - NP_G + KTR_G + GAPNL_G
FNWL_G = ( -NNFWA_G)
NW_G = FNWL_G + Kn_G
FNWLr_G = FNWL_G / Pc
NWr_G = NW_G / Pc
'---- Households (H) ----------------------------------------------------------------------------------
' Pre-tax gross income
Y_H = WB_H + B2_H + FINCOME_H + STR_H + epsilon_H
' Social transfers
STR_H = SBEN_H + OTR_H - SCON_H
' Direct tax
T_H = 0.0902967423925 * Y_H(-1) - 2089.1576608 * UNR + 2498.12965149 * DUM2000 - 86.2552498494 * TIME
' Disposable income, nominal
YD_H = Y_H - T_H
' Social contribution
SCON_H = 33039.8854305 + 0.919199730305 * T_H(-1) + 837.097446244 * TIME - 5543.9088112 * DUM2009
' Social benefit
SBEN_H = 45408.4413795 + 33.0995157691 * UN(-1) - 0.0388229558776 * D(YN) + 1109.82562019 * TIME
' Disposable income, real
YDr_H = YD_H / Pc
' Consumption function (real)
LOG(CR) = 0.156132858221 * LOG(YDR_H) + 0.216990324934 * LOG(NWR_H(-1)) + 0.602940697097 * LOG(CR(-1)) - 0.00704107662539 * CONTAX - 0.0257648670415 * DUM2008 - 0.0298125024088 * DUM2014 - 0.031139982209 * DUM2020
' Consumption, nominal
'
'Cr  = Cn  / Pc
Cn = Cr * Pc
' Capital Formation, housing, nominal
LOG(IR_H) = 0.820960 + 0.915288 * (LOG(IR_H(-1))) + 1.60769 * (d(LOG(YR))) - 0.134807 * (DUM2009)
'         (2.19)   (24.64)                  (3.09)                ( -2.59)
'  OLS   (1995 -2023)   R^2 = 0.960, SD =  0.048230, DW = 2.245
' Capital formation, housing, real
In_H = Ir_H * Ph
' Prices of residential capital stock
Phs = PHS(-1) + KCG_H / Kn_H(-1)
' Depreciation, housing, nominal
D_H = 0.067376744491 * KN_H - 148.44380286 * TIME
' Capital stock dynamics, housing, nominal
Kn_H = Kn_H(-1) * (1 + d(Phs) ) + In_H - D_H
' Real capital stock, housing
Kr_H = Kn_H / Phs
' Saving
S_H = YD_H - Cn + CPEN_H
' Net Lending and net worth
NL_H = S_H - In_H - NP_H + KTR_H + GAPNL_H
FNWL_H = ( - NNFWA_H)
NW_H = FNWL_H + Kn_H
FNWLr_H = FNWL_H / Pc
NWr_H = NW_H / Pc
'---- Rest of World (W) ----------------------------------------------------------------------------
' Import of Japan, real
LOG(MR) = - 14.0124419196 + 2.81388980403 * LOG(YR) - 1.42401937741 * LOG(YR(-1)) + 0.622926830647 * LOG(MR(-1))
' Export of Japan, real
LOG(XR) = 7.16714748724 - 0.469228414229 * LOG(PX / PM) + 0.795050278427 * LOG(YR_W) + 0.163496184226 * DUM2007
' Nominal Export and Import
Xn = Xr * Px
Mn = Mr * Pm
' Net saving of rest of world (Current Account Balance of RoW)
S_W = Mn - Xn + FINCOME_W + WB_W - T_W + STR_W + epsilon_W
' Net Lending and net worth
NL_W = S_W + KTR_W + GAPNL_W
FNWL_W = ( -NNFWA_W)
FNWLr_W = FNWL_W / Pc
'Trade Balance (TB)
TB = Xn - Mn
TBr = Xr - Mr
' Financial Account Balance (FAB) and Foreign Assets (FA) of Japan, nominal
FAB = ( -NL_W)
FA = ( - FNWL_W)
'---- Labour Market, Wage and Prices ---------------------------------------------------------------
' GDP at factor cost
YFn = WB_N + B2
' Wage share
WS = WB_N / YFn
' Unit Labour Cost
ULC = WB_N / Yr
' Employment; Total, Residents and Foreigners
N_N = ( -0.00608893254643 * @PCH(W / PY) + 0.995254451463 * N_N(-1) / YR(-1) + 0.000363725998804 * DUM2020) * YR
'LOG(N_N)  =  - 4.93546  + 0.056811  * (LOG(YR( -1)))  - 0.315333  * (LOG((W( -1)  + W( -2))))  + 0.247912  * (LOG(PY( -1)  / PY( -2)))  + 1.62876  * (LOG(LF))'
'
't-value   ( -8.25) (3.56)               ( -4.64)                       (2.91)                        (16.23)
'  OLS   (1996 -2023)   R^2 = 0.976, SD =  0.003742, DW = 0.863
N_H = N_N - N_W
' Unemployment
UN = LF - N_N
' Unemployment rate
UNR = UN / LF * 100
' Wage Rate
'
W = 3.57636949552 + 2.41396718284 * 1 / UNR + 0.0872247680427 * GDPGAP + 26.3485069223 * @PCH(PC) + 0.903985399331 * W(-1)
WB_H = W * N_H
WB_W = W * N_W
' Potential GDP
gdpmax = exp( - 2.01516441286 + 0.370370456035 * log(kn_g / py) + 0.59265486289 * log(whmax * n_n) + 0.12492831033 * log(135.6667 * kn_n / py))
'GDPGAP
gdpgap = (yr - gdpmax) / gdpmax * 100
PC = 0.560862221519 * TIN_N / YR + 0.0110488271148 * D(W) + 0.0710053516971 * D(PM(-1)) + 0.958502034147 * PC(-1)
PI = - 0.160416391706 + 0.00941927080818 * W - 0.00573098245027 * W(-1) + 0.121363300689 * PM - 0.0504519912963 * PM(-1) + 0.941939758597 * PI(-1) + 0.590316739391 * D(TIN_N / YR)
PH = - 0.300262162671 + 0.0075565154718 * W + 0.247860223297 * PM - 0.243852770932 * PM(-1) + 0.112360647998 * PM(-2) + 0.883025717278 * PH(-1) + 1.74615865071 * D(TIN_N / YR)
PG = - 0.129032145555 + 0.0156292611966 * D(W) + 0.0544111331753 * PM + 1.07498446997 * PG(-1) + 0.0426842081881 * DUM2001
PX = 0.0281156532855 * W(-1) - 0.0284531487373 * W(-2) + 0.498605653133 * PM - 0.442526031284 * PM(-1) + 0.951812589994 * PX(-1)
' Prices of Imports, determined by World Prices and Nominal Effective Exchange Rate
PM = PW / NEER
' Sum of Capital Formations
In_sum = In_H + In_F + In_N + In_G
Ir_sum = In_H / Ph + In_N / Pi + In_F / Pi + In_G / Pi
' Nominal GDP
Yn = Cn + In_sum + Gn + Xn - Mn
' Real GDP
Yr = Cr + In_H / Ph + In_N / Pi + In_F / Pi + In_G / Pi + Gn / Pg + Xr - Mr + Yr_GAP
' GDP Deflator
Py = Yn / Yr
' Nominal Government Consumption
GN = GR * PG
' Real Investments
In_F = Ir_F * PI
IN_G = IR_G * PI
' ******* Flow-of-funds (financial) submodel ***********************************************************************
'---- Nonfinancial Corporations (N) ------------------------------------------------------------------
NSA_N = - 538542.811551 + 0.944444087258 * KN_N + 51019.4100973 * DUM2020
NNFWA_N = NNFWA_N(-1) - NL_N - (NGSHACG_N + NGBACG_N + NDEPACG_N + NLBDACG_N + NEQUACG_N + NPENACG_N)
ASSET_N = NSA_N + NNFWA_N
NLBDA_N / ASSET_N = 0.0413774038104 + 0.243152422843 * D(RRL) - 0.24636333245 * RCHI - 0.559530620504 * IN_N / ASSET_N - 0.378219228122 * NEQUACG_N / ASSET_N + 0.960496059863 * NLBDA_N(-1) / ASSET_N(-1) - 0.209274053463 * NPENA_N(-1) / ASSET_N(-1)
'NEQUA_N/ASSET_N = -0.9785466773 - 0.243160120081*D(RRL) + 0.24636207231*RCHI                        + 0.541992478195*NEQUACG_N/ASSET_N - 0.960657805528*NLBDA_N(-1)/ASSET_N(-1)- 0.673857211429*NPENA_N(-1)/ASSET_N(-1)
NPENA_N / ASSET_N = - 0.0628469981357 + 0.559532952563 * IN_N / ASSET_N - 0.163773116667 * NEQUACG_N / ASSET_N + 0.883132093913 * NPENA_N(-1) / ASSET_N(-1)
NEQUA_N = - ASSET_N - NLBDA_N - NPENA_N
NGSHA_N = NGSHshare_N * NSA_N
NGBA_N = NGBshare_N * NSA_N
NDEPA_N = NDEPshare_N * NSA_N
TOTAL_N = NGSHA_N + NGBA_N + NDEPA_N + NLBDA_N + NEQUA_N + NPENA_N + NNFWA_N
'---- Bank of Japan (CB) ---------------------------------------------------------------------------------------------
' * GOLD is the value of Gold
NGSHA_CB = - (NGSHA_N + NGSHA_F + NGSHA_G + NGSHA_H + NGSHA_W ) + GOLD
' **** SWITCH (NGBA_CB; endogenous/ exogenous) ************************************
'NGBA_CB  =  - ( NGBA_N  + NGBA_F  + NGBA_G  + NGBA_H  + NGBA_W )
NLBDA_CB = - (NGSHA_CB + NGBA_CB + NDEPA_CB + NEQUA_CB + NPENA_CB + NNFWA_CB )
NNFWA_CB = - (NNFWA_N + NNFWA_F + NNFWA_G + NNFWA_H + NNFWA_W) - GOLD
' NDEPA_CB, NEQUA_CB and NPENA_CB = Exogenous
TOTAL_CB = NGSHA_CB + NGBA_CB + NDEPA_CB + NLBDA_CB + NEQUA_CB + NPENA_CB + NNFWA_CB
'---- Other Financial Institutions -------------------------------------------------------------------------------------
NNFWA_F = NNFWA_F(-1) - NL_F - (NGSHACG_F + NGBACG_F + NDEPACG_F + NLBDACG_F + NEQUACG_F + NPENACG_F)
NDEPA_F = - ( NDEPA_N + NDEPA_CB + NDEPA_G + NDEPA_H + NDEPA_W )
NPENA_F = - ( NPENA_N + NPENA_CB + NPENA_G + NPENA_H + NPENA_W )
LIAB_F = - NDEPA_F - NPENA_F - NNFWA_F
NGSHA_F = LIAB_F * ( 0.38746338137 - 1.27902373143 * RRB - 2.42029200782 * RRL - 0.761143692091 * NGBA_F(-1) / LIAB_F(-1) )
NGBA_F = LIAB_F * ( 0.535454452252 * RRB + 0.956517741106 * NGBA_F(-1) / LIAB_F(-1) )
'NLBDA_F=LIAB_F* ( 0.612510422157                         + 2.42025968838*RRL     )
'
'NEQUA_F=LIAB_F*(  0.743589530341*RRB                                  -0.195436900506*NGBA_F(-1)/LIAB_F(-1) )
'
'NLBDA_F  = LIAB_F  - NGSHA_F  - NGBA_F  - NEQUA_F
NLBDA_F = - (NLBDA_N + NLBDA_CB + NLBDA_G + NLBDA_H + NLBDA_W)
NEQUA_F = - (NEQUA_N + NEQUA_CB + NEQUA_G + NEQUA_H + NEQUA_W )
TOTAL_F = NGSHA_F + NGBA_F + NDEPA_F + NLBDA_F + NEQUA_F + NPENA_F + NNFWA_F
'---- General Government ----------------------------------------------------------------------------------------
NNFWA_G = NNFWA_G(-1) - NL_G - (NGSHACG_G + NGBACG_G + NDEPACG_G + NLBDACG_G + NEQUACG_G + NPENACG_G)
NGBA_G = - (NGSHA_G + NDEPA_G + NLBDA_G + NEQUA_G + NPENA_G + NNFWA_G )
TOTAL_G = NGSHA_G + NGBA_G + NDEPA_G + NLBDA_G + NEQUA_G + NPENA_G + NNFWA_G
'---- Households ----------------------------------------------------------------------------------------------------
NNFWA_H = NNFWA_H(-1) - NL_H - (NGSHACG_H + NGBACG_H + NDEPACG_H + NLBDACG_H + NEQUACG_H + NPENACG_H)
NLBDA_H = 54457.6453362 + 309042.976194 * (RL - RM) - 0.92527771901 * IN_H - 0.281895798392 * YDr_H * PC + 0.751398558659 * NLBDA_H(-1)
LIAB_H = - ( NLBDA_H + NNFWA_H)
'NSA_H=LIAB_H*(-0.0877671529838+0.815824468794*D(YDR_H*PC/LIAB_H)+0.387404100114*(YDR_H*PC/LIAB_H)- 0.270827389847*NEQUACG_H/LIAB_H+0.958114163744*NSA_H(-1)/LIAB_H(-1)+0.00113134860371*TIME)
NEQUA_H = LIAB_H * (0.901169611291 + 1.28261783003 * RRM - 1.76198913482 * RPSI - 1.92002221535 * D(YDR_H * PC / LIAB_H) + 0.454209690563 * NEQUACG_H / LIAB_H - 1.38674430426 * NSA_H(-1) / LIAB_H(-1) + 0.00167807493506 * TIME)
NPENA_H = LIAB_H * (0.186597841488 - 1.2826212692 * RRM + 1.76198560628 * RPSI + 1.10419774401 * D(YDR_H * PC / LIAB_H) - 0.387417872391 * (YDR_H * PC / LIAB_H) - 0.183382302181 * NEQUACG_H / LIAB_H + 0.42863030574 * NSA_H(-1) / LIAB_H(-1) - 0.00280927978091 * TIME)
NSA_H = LIAB_H - ( NEQUA_H + NPENA_H)
NGSHA_H = NGSHshare_H * NSA_H
NGBA_H = NGBshare_H * NSA_H
NDEPA_H = NDEPshare_H * NSA_H
TOTAL_H = NGSHA_H + NGBA_H + NDEPA_H + NLBDA_H + NEQUA_H + NPENA_H + NNFWA_H
'---- World ------------------------------------------------------------------------------------------------------------
NNFWA_W = NNFWA_W(-1) - NL_W - (NGSHACG_W + NGBACG_W + NDEPACG_W + NLBDACG_W + NEQUACG_W + NPENACG_W)
NSA_W = NNFWA_W * ( 0.0385616031094 + 0.875608908424 * NSA_W(-1) / NNFWA_W(-1))
NLBDA_W = NNFWA_W * ( - 0.85933310691 + 2.22960485647 * (RL - I_US) - 0.26163379119 * D(NEER) + 0.34806892821 * NEER - 1.38678017386 * NEQUACG_W / NNFWA_W - 0.485842960709 * NSA_W(-1) / NNFWA_W(-1) + 0.634596115343 * NLBDA_W(-1) / NNFWA_W(-1))
'NEQUA_W=NNFWA_W *( -0.179326635971 - 2.22965908266*(RL-I_US)  + 0.261851341075*D(NEER) - 0.348135435063*NEER +1.38692091973*NEQUACG_W/NNFWA_W-0.389787943914*NSA_W(-1)/NNFWA_W(-1)-0.634856187526*NLBDA_W(-1)/NNFWA_W(-1))
NEQUA_W = - (NSA_W + NLBDA_W + NNFWA_W)
NGSHA_W = NGSHshare_W * NSA_W
NGBA_W = NGBshare_W * NSA_W
NDEPA_W = NDEPshare_W * NSA_W
TOTAL_W = NGSHA_W + NGBA_W + NDEPA_W + NLBDA_W + NEQUA_W + NPENA_W + NNFWA_W
'---- Check Sum ------------------------------------------------------------------------------------------------------
NGSHA_SUM = NGSHA_N + NGSHA_CB + NGSHA_F + NGSHA_G + NGSHA_H + NGSHA_W
NGBA_SUM = NGBA_N + NGBA_CB + NGBA_F + NGBA_G + NGBA_H + NGBA_W
NDEPA_SUM = NDEPA_N + NDEPA_CB + NDEPA_F + NDEPA_G + NDEPA_H + NDEPA_W
NLBDA_SUM = NLBDA_N + NLBDA_CB + NLBDA_F + NLBDA_G + NLBDA_H + NLBDA_W
NEQUA_SUM = NEQUA_N + NEQUA_CB + NEQUA_F + NEQUA_G + NEQUA_H + NEQUA_W
NPENA_SUM = NPENA_N + NPENA_CB + NPENA_F + NPENA_G + NPENA_H + NPENA_W
NNFWA_SUM = NNFWA_N + NNFWA_CB + NNFWA_F + NNFWA_G + NNFWA_H + NNFWA_w
Total_sum = total_N + total_CB + total_F + total_G + total_H + total_W
'---- Interest rates and dividend rates -----------------------------------------------------------------------------
' *** SWITCH (endogenous/exogenous) ************************
rB = RrB + (PC - PC(-1)) / PC(-1)
RM = 0.000989109388342 + 1.03622784438 * RB - 0.78118793737 * RB(-1) + 0.505888254273 * RM(-1)
RL = 0.0146164569634 + 1.12490792852 * RB + 0.0115728196955 * DUM2022 + 0.0115728196955 * DUM2023
PSI = 0.01652967307 + 0.550202649696 * RB
CHI = 0.0167534260504 - 0.194830747896 * RB - 0.190078018037 * B2_N / 10^6 + 0.202900640038 * B2_N(-1) / 10^6 + 0.0952710711814 * D(PC(-1)) + 0.418268427126 * D(CHI(-1)) + 0.00455813631579 * DUM2009
RrH = - (PC - PC(-1)) / PC(-1)
RrM = rM - (PC - PC(-1)) / PC(-1)
RrL = rL - (PC - PC(-1)) / PC(-1)
Rchi = chi - (PC - PC(-1)) / PC(-1)
Rpsi = psi - (PC - PC(-1)) / PC(-1)
'---- MB and MS ---------------------------------------------------------------------
mb = - ngsha_cb - ngsha_g
ms = ngsha_n + ngsha_h + ngsha_w + ndepa_n + ndepa_g + ndepa_h + ndepa_w
' **** END of MODEL ***********************
