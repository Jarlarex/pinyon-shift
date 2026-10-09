# Car list check (EU + v4 + DLC)

Checked 2026-10-09 on the EU disc with title update v4 and all 22 supplied DLC packages installed.

**Result: every car on the reference list is in the game's database. None are missing.**

| Group | Reference list | In this install |
| --- | --- | --- |
| Base game: Autoshow, barn finds, unicorns | 145 | 145 |
| DLC: 15 packs and 2 promotional cars | 73 | 73 |
| Traffic | 18 | 18 |
| **Total** | **236** | **236** |

## Method

- **In the game:** every `Data_Car` row of the v4 `gamedb.slt` and of each installed package's `*_merge.slt`
  (251 rows), named from the English `Data_Car.str` and `List_CarMake.str` string tables of the disc and
  each package.
- **Reference:** the [Forza Wiki car list](https://forza.fandom.com/wiki/Forza_Horizon/Cars) (218 cars plus
  18 traffic vehicles), matched by year, make and model.
- Four names differ only in spelling or variant and were matched by hand: Citroën DS 3 Racing (`DS3` in game),
  Ford GT40 Mk II (`MkII`), Ford Explorer Eddie Bauer Edition (`Explorer`) and Dodge Charger SRT8 LCE
  (`DOD_LCEChargerSRT8_12`).

## Notes

- There is no Dodge Challenger SRT8 392 Rockstar car. The only Rockstar promotional car is the 2013 Ford Shelby
  GT500 Rockstar Energy Edition, which ships in the November Bondurant package. The base 2012 Challenger SRT8 392
  is in the Autoshow. A Challenger Rockstar *livery* belongs to a package that has not been supplied.
- The reference list files some cars under a different pack than the one that ships them. The Devon GTX,
  Joss JT1 and Pagani Zonda Cinque Roadster (listed as Season Pass) ship in the February, March and January
  packs. The LCE livery cars ship in the October pack.
- "Package" in the table below is the installed package whose database adds the car.

## Every listed car

| Car | Reference source | Game ID and media name | Package |
| --- | --- | --- | --- |
| 2010 Abarth 500 esseesse | Autoshow | `1115` `FIA_500AbarthSS_10` | base game |
| 1968 Abarth 595 esseesse | Autoshow | `1545` `FIA_595_68` | base game |
| 2007 Alfa Romeo 8C Competizione | Autoshow | `1032` `ALF_8C_08` | base game |
| 2012 Ascari KZ1R | Autoshow | `1451` `ASC_KZ1R_12` | base game |
| 2010 Aston Martin One-77 | Autoshow | `1181` `AST_One77_10` | base game |
| 2011 Aston Martin V12 Zagato (Villa d'Este) | Autoshow | `1483` `AST_V12Zagato_12` | base game |
| 2011 Audi R8 GT Coupe | Autoshow | `1551` `AUD_R8GT_11` | base game |
| 2006 Audi RS 4 | Autoshow | `419` `AUD_RS4_06` | base game |
| 1983 Audi Sport quattro | Autoshow | `633` `AUD_SportQuattro_83` | base game |
| 2010 Audi TT RS Coupe | Autoshow | `1220` `AUD_TTRS_10` | base game |
| 2011 BMW 1 Series M Coupe | Autoshow | `1385` `BMW_1M_11` | base game |
| 1973 BMW 2002 Turbo | Autoshow | `1269` `BMW_2002Turbo_73` | base game |
| 1991 BMW M3 | Autoshow | `642` `BMW_M3E30_91` | base game |
| 2008 BMW M3 | Autoshow | `1011` `BMW_M3E92_08` | base game |
| 2012 BMW M5 | Autoshow | `1388` `BMW_M5_12` | base game |
| 2013 BMW M6 Coupe | Autoshow | `1563` `BMW_M6_13` | base game |
| 2012 BMW Z4 sDrive28i | Autoshow | `1535` `BMW_Z4sDrive28i_12` | base game |
| 2012 Bentley Continental GT | Autoshow | `1528` `BEN_CONTINENTALGT_11` | base game |
| 2011 Bugatti Veyron Super Sport | Autoshow | `1328` `BUG_VeyronSS_11` | base game |
| 2011 Cadillac CTS-V Coupe | Autoshow | `1255` `CAD_CTSVCoupe_11` | base game |
| 1969 Chevrolet Camaro SS Coupe | Autoshow | `289` `CHE_CamaroSS_69` | base game |
| 2012 Chevrolet Camaro ZL1 | Autoshow | `1419` `CHE_CamaroZL1_12` | base game |
| 2010 Chevrolet Corvette Grand Sport Convertible | Autoshow | `1527` `CHE_CORVETTEGSC_10` | base game |
| 1967 Chevrolet Corvette Stingray 427 | Autoshow | `312` `CHE_CorvetteStingray_67` | base game |
| 2009 Chevrolet Corvette ZR1 | Autoshow | `1069` `CHE_CorvetteZR1_09` | base game |
| 1964 Chevrolet Impala SS 409 | Autoshow | `1300` `CHE_ImpalaSS_64` | base game |
| 2011 Citroën DS 3 Racing | Autoshow | `1537` `CIT_DS3Racing_11` | base game |
| 2012 Dodge Challenger SRT8 392 | Autoshow | `1557` `DOD_ChallengerSRT8392_12` | base game |
| 1969 Dodge Charger R/T | Autoshow | `513` `DOD_ChargerRT_69` | base game |
| 2012 Dodge Charger SRT8 | Autoshow | `1422` `DOD_ChargerSRT8_12` | base game |
| 2012 Eagle Speedster | Autoshow | `1519` `EAE_Speedster_12` | base game |
| 1957 Ferrari 250 California | Autoshow | `1271` `FER_250GT_60` | base game |
| 1962 Ferrari 250 GTO | Autoshow | `249` `FER_250GTO_64` | base game |
| 2007 Ferrari 430 Scuderia | Autoshow | `1022` `FER_F430Scuderia_07` | base game |
| 2011 Ferrari 458 Spider | Autoshow | `1556` `FER_458Spider_12` | base game |
| 2010 Ferrari 599XX | Autoshow | `1171` `FER_599XX_10` | base game |
| 2009 Ferrari California | Autoshow | `1062` `FER_California_09` | base game |
| 2002 Ferrari Enzo Ferrari | Autoshow | `333` `FER_Enzo_02` | base game |
| 1995 Ferrari F355 Challenge | Autoshow | `339` `FER_355Challenge_95` | base game |
| 1987 Ferrari F40 | Autoshow | `340` `FER_F40_87` | base game |
| 1989 Ferrari F40 Competizione | Autoshow | `1023` `FER_F40Competizione_89` | base game |
| 1995 Ferrari F50 | Autoshow | `342` `FER_F50_95` | base game |
| 1996 Ferrari F50 GT | Autoshow | `1020` `FER_F50GT_96` | base game |
| 2011 Ferrari FF | Autoshow | `1389` `FER_F151_11` | base game |
| 2005 Ferrari FXX | Autoshow | `1006` `FER_FXX_05` | base game |
| 1984 Ferrari GTO | Autoshow | `358` `FER_GTO_84` | base game |
| 2011 Ford F-150 SVT Raptor | Autoshow | `1460` `FOR_SVTRaptor_12` | base game |
| 2010 Ford Focus RS500 | Autoshow | `1536` `FOR_FocusRS500_10` | base game |
| 2013 Ford Focus ST | Autoshow | `1399` `FOR_FocusST_12` | base game |
| 2005 Ford GT | Autoshow | `348` `FOR_GT_05` | base game |
| 1966 Ford GT40 Mk II | Autoshow | `355` `FOR_GT40_66` | base game |
| 1970 Ford Mustang Boss 429 | Autoshow | `404` `FOR_MustangBOSS429_70` | base game |
| 1985 Ford RS200 Evolution | Autoshow | `1108` `FOR_RS200Evolution_87` | base game |
| 2013 Ford Shelby GT500 | Autoshow | `1553` `FOR_ShelbyGT500_13` | base game |
| 1987 Ford Sierra Cosworth RS500 | Autoshow | `1293` `FOR_RS500_87` | base game |
| 2009 Gumpert Apollo S | Autoshow | `1237` `GUM_ApolloS_10` | base game |
| 2012 Hennessey Venom GT | Autoshow | `1564` `HEN_VenomGT_12` | base game |
| 2004 Honda Civic Type-R | Autoshow | `302` `HON_CivicR_04` | base game |
| 2002 Honda Integra Type-R | Autoshow | `369` `HON_IntegraR_02` | base game |
| 2005 Honda NSX-R GT | Autoshow | `569` `HON_NSXRGT_05` | base game |
| 2003 Honda S2000 | Autoshow | `427` `HON_S2000_03` | base game |
| 2013 Hyundai Genesis Coupe | Autoshow | `1547` `HYU_GenesisCoupe_13` | base game |
| 2012 Infiniti IPL G Coupe | Autoshow | `1559` `INF_IPLGCoupe_12` | base game |
| 1961 Jaguar E-type S1 | Autoshow | `336` `JAG_Etype_61` | base game |
| 2012 Jaguar XKR-S | Autoshow | `1496` `JAG_XKRS_12` | base game |
| 2012 Jeep Grand Cherokee SRT8 | Autoshow | `1554` `CHR_JeepGCSRT8_12` | base game |
| 2009 Koenigsegg CCX-R Edition | Autoshow | `1521` `KOE_CCXR_09` | base game |
| 2012 Lamborghini Aventador LP700-4 | Autoshow | `1398` `LAM_LP7004_12` | base game |
| 1988 Lamborghini Countach LP5000 QV | Autoshow | `316` `LAM_Countach_88` | base game |
| 1997 Lamborghini Diablo SV | Autoshow | `325` `LAM_DiabloSV_97` | base game |
| 2011 Lamborghini Gallardo LP570-4 Superleggera | Autoshow | `1322` `LAM_GallardoLP570_11` | base game |
| 1967 Lamborghini Miura P400 | Autoshow | `637` `LAM_MiuraP400_67` | base game |
| 2010 Lamborghini Murciélago LP 670-4 SV | Autoshow | `1173` `LAM_LP6704SV_10` | base game |
| 2009 Lamborghini Reventón Roadster | Autoshow | `1538` `LAM_ReventonRoadster_09` | base game |
| 1992 Lancia Delta Integrale EVO | Autoshow | `323` `LAN_Delta_92` | base game |
| 1986 Lancia Delta S4 | Autoshow | `1534` `LAN_DeltaS4_86` | base game |
| 1974 Lancia Stratos HF Stradale | Autoshow | `458` `LAN_Stratos_74` | base game |
| 2012 Land Rover Range Rover Supercharged | Autoshow | `1525` `LR_RangeRover_12` | base game |
| 2009 Lexus IS F | Autoshow | `1071` `LEX_ISF_09` | base game |
| 2010 Lexus LF-A | Autoshow | `1260` `LEX_LFA_10` | base game |
| 2009 Lotus 2-Eleven | Autoshow | `1187` `LOT_2Eleven_09` | base game |
| 2011 Lotus Evora S | Autoshow | `1526` `LOT_EVORAS_11` | base game |
| 2006 Lotus Exige Cup 240 | Autoshow | `454` `LOT_Exige240_06` | base game |
| 1965 MINI Cooper S | Autoshow | `1520` `AUS_MiniCooperS_65` | base game |
| 2011 MINI Cooper S | Autoshow | `1522` `MIN_Coopers_11` | base game |
| 2010 Maserati GranTurismo S | Autoshow | `1304` `MAS_GranTurismoS_10` | base game |
| 2008 Maserati MC12 Versione Corsa | Autoshow | `1539` `MAS_MC12Corsa_08` | base game |
| 1994 Mazda MX-5 Miata | Autoshow | `1110` `MAZ_Miata_94` | base game |
| 1997 Mazda RX-7 | Autoshow | `424` `MAZ_RX7_97` | base game |
| 2004 Mazda RX-8 Mazdaspeed | Autoshow | `426` `MAZ_RX8Mazdaspeed_04` | base game |
| 1997 McLaren F1 GT | Autoshow | `338` `MCL_F1GT_97` | base game |
| 2011 McLaren MP4-12C | Autoshow | `1130` `MCL_MP412C_11` | base game |
| 2012 Mercedes-Benz C63 AMG Black Series | Autoshow | `1500` `MER_C63AMG_12` | base game |
| 2009 Mercedes-Benz ML63 AMG | Autoshow | `1051` `MER_ML63AMG_09` | base game |
| 2012 Mercedes-Benz S65 AMG | Autoshow | `1540` `MER_S65AMG_12` | base game |
| 2009 Mercedes-Benz SL 65 AMG Black Series | Autoshow | `1090` `MER_SL65AMG_09` | base game |
| 1999 Mitsubishi Lancer Evolution VI GSR | Autoshow | `375` `MIT_LancerEvoVIGSR_99` | base game |
| 2008 Mitsubishi Lancer Evolution X GSR | Autoshow | `1009` `MIT_LancerEvoXGSR_08` | base game |
| 2008 Mitsubishi Lancer Evolution X GSR LCE | Autoshow | `1575` `MIT_LCELancerEvoXGSR_08` | October Car Pack |
| 1969 Nissan Fairlady Z 432 | Autoshow | `343` `NIS_Fairlady432Z_69` | base game |
| 2012 Nissan GT-R Black Edition | Autoshow | `1558` `NIS_GTR_12` | base game |
| 2000 Nissan Silvia Spec-R | Autoshow | `441` `NIS_SilviaSpecR_00` | base game |
| 1971 Nissan Skyline 2000GT-R | Autoshow | `1042` `NIS_Skyline2000GTR_71` | base game |
| 2002 Nissan Skyline GT-R V-Spec II | Autoshow | `445` `NIS_SkylineGTRVSpecII_02` | base game |
| 2010 Noble M600 | Autoshow | `1253` `NOB_M600_10` | base game |
| 2010 Pagani Zonda R | Autoshow | `1175` `PAG_ZondaR_10` | base game |
| 1984 Peugeot 205 Turbo 16 | Autoshow | `1533` `PEU_205T16_84` | base game |
| 1977 Pontiac Firebird Trans Am | Autoshow | `1276` `PON_FirebirdTransAm_77` | base game |
| 1969 Pontiac GTO Judge | Autoshow | `1309` `PON_GTOJudge_69` | base game |
| 1987 RUF CTR Yellowbird | Autoshow | `1516` `RUF_Yellowbird_87` | base game |
| 2011 RUF RGT-8 | Autoshow | `1432` `RUF_RGT8_11` | base game |
| 2011 Radical SR8 RX | Autoshow | `1247` `RAD_SR8LM_10` | base game |
| 2010 SSC Ultimate Aero | Autoshow | `1251` `SSC_UltimateAero_10` | base game |
| 2004 Saleen S7 | Autoshow | `432` `SAL_S7_04` | base game |
| 2013 Scion FR-S | Autoshow | `1548` `SCI_FRS_13` | base game |
| 1998 Subaru Impreza 22B STi | Autoshow | `363` `SUB_Impreza22b_98` | base game |
| 2011 Subaru WRX STI | Autoshow | `1323` `SUB_WRXSTi_11` | base game |
| 2005 TVR Sagaris | Autoshow | `433` `TVR_Sagaris_05` | base game |
| 1985 Toyota Sprinter Trueno GT Apex | Autoshow | `455` `TOY_Sprinter_85` | base game |
| 1998 Toyota Supra RZ | Autoshow | `461` `TOY_SupraRZ_98` | base game |
| 2012 Ultima GTR | Autoshow | `1455` `ULT_GTR_12` | base game |
| 2013 Viper GTS | Autoshow | `1544` `VIP_Viper_13` | base game |
| 2010 Viper SRT10 ACR-X | Autoshow | `1555` `DOD_ViperSRT10ACRX_12` | base game |
| 1967 Volkswagen Beetle | Autoshow | `1523` `VW_BEETLE_68` | base game |
| 1995 Volkswagen Corrado VR6 | Autoshow | `309` `VW_Corrado_95` | base game |
| 1992 Volkswagen Golf GTi 16v Mk2 | Autoshow | `353` `VW_GolfGTi16vMk2_92` | base game |
| 1984 Volkswagen Rabbit GTI | Autoshow | `1107` `VW_RabbitGTI_84` | base game |
| 2011 Volkswagen Scirocco R | Autoshow | `1428` `VW_SciroccoR_11` | base game |
| 2011 Volkswagen Scirocco R LCE | Autoshow | `1573` `VW_LCESciroccoR_11` | October Car Pack |
| 1964 Aston Martin DB5 Vantage | Barn Find | `1105` `AST_DB5Vantage_64` | base game |
| 1958 Aston Martin DBR1 | Barn Find | `1386` `AST_DBR1_58` | base game |
| 1981 BMW M1 | Barn Find | `1040` `BMW_M1_81` | base game |
| 1992 Bugatti EB110 SS | Barn Find | `1219` `BUG_EB110SS_92` | base game |
| 1957 Ferrari 250 Testa Rossa | Barn Find | `1154` `FER_250TestaRossa_57` | base game |
| 1956 Jaguar D-Type | Barn Find | `1301` `JAG_DType_56` | base game |
| 1954 Mercedes-Benz 300SL Gullwing Coupe | Barn Find | `251` `MER_300SL_54` | base game |
| 1971 Plymouth Cuda 426 HEMI | Barn Find | `1277` `CHR_Cuda426_71` | base game |
| 1965 Shelby Cobra Daytona Coupe | Barn Find | `1155` `SHE_CobraDaytona_65` | base game |
| 1969 Ferrari Dino 246 GT | Unicorn | `326` `FER_Dino246_69` | base game |
| 2009 Ford Fiesta Zetec S | Unicorn | `1082` `FOR_Fiesta_09` | base game |
| 1991 Honda CR-X SiR | Unicorn | `320` `HON_CRXsi_91` | base game |
| 1971 Lotus Elan Sprint | Unicorn | `330` `LOT_ElanSprint_72` | base game |
| 2012 MINI John Cooper Works Coupé | Unicorn | `1488` `MIN_CoupeJCW_12` | base game |
| 2010 Mazda MX-5 Superlight | Unicorn | `1233` `MAZ_MX5SL_10` | base game |
| 2010 Saleen S5S Raptor | Unicorn | `1197` `SAL_S5SRaptor_10` | base game |
| 1956 Ford F100 | 1000 Club | `1682` `FOR_F100_56` | 1000 Club Expansion Pack |
| 1995 RUF CTR2 | 1000 Club | `1515` `RUF_CTR2_95` | 1000 Club Expansion Pack |
| 2011 Alfa Romeo TZ3 Stradale Zagato | April Top Gear | `1656` `ALF_ZagatoTZ3Stradale_12` | April TopGear Car Pack |
| 2012 Aston Martin Vanquish | April Top Gear | `1683` `AST_Vanquish_13` | April TopGear Car Pack |
| 2002 BMW M3 GTR | April Top Gear | `1679` `BMW_M3GTR_HZN_05` | April TopGear Car Pack |
| 2012 Bowler EXR-S | April Top Gear | `1494` `BOW_NemesisEXR_12` | April TopGear Car Pack |
| 2011 Ford Transit SuperSportVan | April Top Gear | `1477` `FOR_TransitSSV_11` | April TopGear Car Pack |
| 1998 Mercedes-Benz AMG Mercedes CLK GTR | April Top Gear | `1685` `MER_CLKGTR_HZN_98` | April TopGear Car Pack |
| 1971 AMC Javelin-AMX | December IGN | `1267` `AMC_JavelinAMX_71` | December IGN Car Pack |
| 2008 Aston Martin DBS | December IGN | `1081` `AST_DBS_09` | December IGN Car Pack |
| 2012 Ferrari F12berlinetta | December IGN | `1608` `FER_F12_13` | December IGN Car Pack |
| 2011 Ford F-150 SVT Raptor: Halo Edition | December IGN | `1625` `FOR_SVTRaptorHALO_12` | December IGN Car Pack |
| 2006 Ford GTX1 | December IGN | `1623` `FOR_GTX1_06` | December IGN Car Pack |
| 2006 HUMMER H1 Alpha Open Top | December IGN | `1624` `HUM_H1AlphaOpenTop_06` | December IGN Car Pack |
| 1993 McLaren F1 | December IGN | `1314` `MCL_F1_93` | December IGN Car Pack |
| 1991 Ferrari 512 TR | February Jalopnik | `1675` `FER_512TR_HZN_91` | February Jalopnik Car Pack |
| 1966 Ford Country Squire | February Jalopnik | `1484` `FOR_CountrySquire_66` | February Jalopnik Car Pack |
| 1973 Mazda RX-3 | February Jalopnik | `1514` `MAZ_RX3_73` | February Jalopnik Car Pack |
| 1970 Nissan Datsun 510 | February Jalopnik | `1104` `NIS_510_70` | February Jalopnik Car Pack |
| 2013 Subaru BRZ | February Jalopnik | `1655` `SUB_BRZ_13` | February Jalopnik Car Pack |
| 2012 Toyota FJ Cruiser | February Jalopnik | `1651` `TOY_FJCruiser_12` | February Jalopnik Car Pack |
| 1986 Honda Civic Si | Honda Challenge | `1650` `HON_CivicSi_86` | Honda Challenge Car Pack |
| 2013 Honda Civic Si Coupe | Honda Challenge | `1648` `HON_CivicSi_13` | Honda Challenge Car Pack |
| 2012 Honda HPD Fit | Honda Challenge | `1649` `HON_HPDRallyFit_10` | Honda Challenge Car Pack |
| 2012 Cadillac Escalade ESV | January Recaro | `1637` `CAD_Escalade_12` | January Recaro Car Pack |
| 1995 Ford Mustang Cobra R | January Recaro | `1510` `FOR_Mustang_95` | January Recaro Car Pack |
| 1983 GMC Vandura G-1500 | January Recaro | `1636` `GMC_Vandura_83` | January Recaro Car Pack |
| 2012 Lexus LFA Nürburgring Edition | January Recaro | `1602` `LEX_LFANurburgring_12` | January Recaro Car Pack |
| 2012 Lotus Exige S | January Recaro | `1607` `LOT_ExigeS_12` | January Recaro Car Pack |
| 2005 Mercedes-Benz SLR | January Recaro | `447` `MER_SLR_05` | January Recaro Car Pack |
| 1983 Audi Sport quattro: LCE | LCE Livery | `1572` `AUD_LCESportQuattro_83` | October Car Pack |
| 2012 Dodge Charger SRT8 LCE | LCE Livery | `1576` `DOD_LCEChargerSRT8_12` | October Car Pack |
| 2011 Ford F-150 SVT Raptor LCE | LCE Livery | `1574` `FOR_LCESVTRaptor_12` | October Car Pack |
| 2013 Audi RS 4 Avant | March Meguiar's | `1681` `AUD_RS4Avant_13` | March Meguiar's Car Pack |
| 2013 BMW M135i | March Meguiar's | `1621` `BMW_M135i_13` | March Meguiar's Car Pack |
| 2003 Ferrari Challenge Stradale | March Meguiar's | `1676` `FER_360Challenge_HZN_03` | March Meguiar's Car Pack |
| 2012 Mercedes-Benz G65 AMG | March Meguiar's | `1684` `MER_G65AMG_13` | March Meguiar's Car Pack |
| 1998 Nissan R390 | March Meguiar's | `1680` `NIS_R390_HZN_98` | March Meguiar's Car Pack |
| 2004 Peugeot 206 RC | March Meguiar's | `248` `PEU_206RC_04` | March Meguiar's Car Pack |
| 2010 BMW M3 GTS | November Bondurant | `1598` `BMW_M3GTS_10` | November Bondurant Car Pack |
| 2012 Jeep Wrangler Rubicon | November Bondurant | `1571` `JEE_Wrangler_12` | November Bondurant Car Pack |
| 2012 Lamborghini Gallardo LP570-4 Spyder Performante | November Bondurant | `1601` `LAM_GallardoLP570Spyder_12` | November Bondurant Car Pack |
| 1993 Nissan 240SX SE | November Bondurant | `1282` `NIS_240SX_94` | November Bondurant Car Pack |
| 2012 Shelby 1000 | November Bondurant | `1605` `SHE_1000_12` | November Bondurant Car Pack |
| 1965 Shelby Cobra 427 S/C | November Bondurant | `306` `SHE_Cobra427_65` | November Bondurant Car Pack |
| 2010 Alfa Romeo 8C Spider | October | `1597` `ALF_8CSpider_10` | October Car Pack |
| 1957 Chevrolet Bel Air | October | `1459` `CHE_BelAir_57` | October Car Pack |
| 2012 Ferrari 599XX Evoluzione | October | `1599` `FER_599XXEvolution_12` | October Car Pack |
| 2013 Ford Mustang Boss 302 | October | `1569` `FOR_MustangBoss302_13` | October Car Pack |
| 2012 Gumpert Apollo Enraged | October | `1600` `GUM_ApolloEnraged_12` | October Car Pack |
| 2012 Lamborghini Aventador J | October | `1583` `LAM_AventadorJ_12` | October Car Pack |
| 2012 Aston Martin Virage | Pre-Order | `1416` `AST_Virage_12` | Pre-Order Car Pack |
| 2009 Ferrari 458 Italia | Pre-Order | `1131` `FER_F142_10` | Pre-Order Car Pack |
| 2011 Mercedes-Benz SLS AMG | Pre-Order | `1202` `MER_SLSAMG_11` | Pre-Order Car Pack |
| 2010 Nissan 370Z | Pre-Order | `1103` `NIS_370Z_10` | Pre-Order Car Pack |
| 2010 Volkswagen Golf R | Pre-Order | `1231` `VW_GolfR_10` | Pre-Order Car Pack |
| 2013 Ford Mustang Boss 302: Pizza Hut Edition | Promotional: Redeem a Mustang Boss Pizza Hut code | `1686` `FOR_MustangBoss302_PZA_13` | 2013 Ford Mustang Boss 302  - Pizza Hut Edition |
| 2013 Ford Shelby GT500 Rockstar Energy Edition | Promotional: Redeem a Shelby GT500 Rockstar Energy code | `1606` `FOR_ShelbyGT500LCE_13` | November Bondurant Car Pack |
| 1992 Ford Escort RS Cosworth | Rally Expansion | `1272` `FOR_EscortRSCosworth_92` | Rally Expansion Pack |
| 1982 Lancia 037 Stradale | Rally Expansion | `1295` `LAN_037Stradale_82` | Rally Expansion Pack |
| 2004 Mitsubishi Lancer Evolution VIII MR | Rally Expansion | `378` `MIT_LancerEvoVIIIMR_04` | Rally Expansion Pack |
| 2005 Subaru Impreza WRX STi | Rally Expansion | `365` `SUB_WRXSTi_05` | Rally Expansion Pack |
| 1992 Toyota Celica GT-Four RC ST185 | Rally Expansion | `1517` `TOY_CelicaST185_90` | Rally Expansion Pack |
| 2010 Devon GTX | Season Pass | `1243` `DEV_GTX_10` | February Jalopnik Car Pack |
| 2003 Ford SVT Focus | Season Pass | `346` `FOR_FocusSVT_03` | Rally Expansion Pack |
| 2010 Joss JT1 | Season Pass | `1244` `JOS_JT1_10` | March Meguiar's Car Pack |
| 2006 Lamborghini Miura Concept | Season Pass | `636` `LAM_Miura_06` | Season Pass: 2006 Lamborghini Miura Concept |
| 2009 Pagani Zonda Cinque Roadster | Season Pass | `1369` `PAG_ZondaCinque_09` | January Recaro Car Pack |
| 2012 Audi R8 GT Spyder | VIP | `1552` `AUD_R8GTSpyder_12` | VIP Membership & Cars Pack |
| 2011 Koenigsegg Agera | VIP | `1397` `KOE_Agera_11` | VIP Membership & Cars Pack |
| 2011 Lamborghini Sesto Elemento | VIP | `1392` `LAM_SestoElemento_11` | VIP Membership & Cars Pack |
| 2012 Pagani Huayra | VIP | `1427` `PAG_Huayra_12` | VIP Membership & Cars Pack |
| 2011 RUF Rt 12 R | VIP | `1434` `RUF_Rt12R_11` | VIP Membership & Cars Pack |
| 2004 Audi A4 Avant | Traffic | `1531` `AUD_A4Avant_04` | base game |
| 2012 Bus Tour Bus | Traffic | `1529` `BUS_TOUR_12` | base game |
| 2005 Chevrolet Express 2500 Cargo Van | Traffic | `1549` `CHE_Express2500Cargo_05` | base game |
| 2004 Chrysler PT Cruiser GT | Traffic | `414` `CHR_PTCruiser_04` | base game |
| 1999 Dodge Durango SLT | Traffic | `1550` `DOD_Durango_99` | base game |
| 2010 Ford Explorer Eddie Bauer Edition | Traffic | `1541` `FOR_Explorer_10` | base game |
| 2008 Ford F-350 Super Duty XLT | Traffic | `1542` `FOR_F350SuperDuty_08` | base game |
| 2005 Ford Focus ZX4 | Traffic | `1543` `FOR_FocusZX4_05` | base game |
| 2010 Ford Taurus SHO | Traffic | `1241` `FOR_TaurusSHO_10` | base game |
| 2001 GMC Yukon XL Denali | Traffic | `1560` `GMC_YukonXL_01` | base game |
| 2012 Kenworth T440 | Traffic | `1562` `KEN_T440_12` | base game |
| 2011 Nissan Leaf | Traffic | `1365` `NIS_Leaf_11` | base game |
| 2007 Toyota Camry | Traffic | `1532` `TOY_Camry_07` | base game |
| 1995 Toyota Corolla DX | Traffic | `1546` `TOY_CorollaDX_95` | base game |
| 2011 Toyota Prius | Traffic | `1340` `TOY_Prius_11` | base game |
| 2004 Toyota RAV4 Sport | Traffic | `1530` `TOY_RAV4Sport_04` | base game |
| 2004 Volkswagen Beetle | Traffic | `282` `VW_Beetle_04` | base game |
| 2012 Volvo XC70 | Traffic | `1561` `VOL_XC70_12` | base game |

## Entries in the game but not on the list

These 15 rows are internal copies that cannot be bought or selected: 10 Rally event and AI copies of existing cars,
3 showcase-event cars, an Xbox Live Indie-event Corrado and a placeholder.

| Game ID and media name | Car | Package |
| --- | --- | --- |
| `1566` `AUS_ShowCaseMiniCooperS_65` | 1965 MINI Cooper S | base game |
| `1568` `PEU_ShowCase205T16_84` | 1984 Peugeot 205 Turbo 16 | base game |
| `1565` `VW_IECorrado_95` | 1995 Volkswagen Corrado VR6 | base game |
| `1215` `NUL_Car_00` | 2000 BMW NULL CAR | base game |
| `1567` `FIA_ShowCase500AbarthSS_10` | 2010 Abarth 500 esseesse | base game |
| `1627` `AUS_MiniCooperS_65` | 1965 MINI Cooper S | Rally Expansion Pack |
| `1629` `PEU_205T16_84` | 1984 Peugeot 205 Turbo 16 | Rally Expansion Pack |
| `1628` `TOY_Sprinter_85` | 1985 Toyota Sprinter Trueno GT Apex | Rally Expansion Pack |
| `1632` `FOR_RS200Evolution_87` | 1985 Ford RS200 Evolution | Rally Expansion Pack |
| `1630` `LAN_DeltaS4_86` | 1986 Lancia Delta S4 | Rally Expansion Pack |
| `1626` `SUB_WRXSTi_05` | 2005 Subaru Impreza WRX STi | Rally Expansion Pack |
| `1635` `FER_FXX_05` | 2005 Ferrari FXX | Rally Expansion Pack |
| `1631` `AUD_RS4_06` | 2006 Audi RS 4 | Rally Expansion Pack |
| `1633` `LAM_LP7004_12` | 2012 Lamborghini Aventador LP700-4 | Rally Expansion Pack |
| `1634` `ULT_GTR_12` | 2012 Ultima GTR | Rally Expansion Pack |
