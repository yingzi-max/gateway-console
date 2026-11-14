"""批量前台源码目录（由 t3-v3.tar.gz 提取，仅 JP，共 167 个站点）。

每个站点对应 sources/<站点名>/ 目录，入口统一为 index.html。
字段与 app.py 的 SOURCE_CATALOG 完全一致，导入后 merge 进去即可。
"""

from pathlib import Path

SOURCES_DIR = Path(__file__).resolve().parent / "sources"
ENTRY = "index.html"

# 站点名 	 国家码(空=通用) 	 描述 	 预览图相对路径(空=显示 HTML)
_RAW = """
_test_acom_jp_card	JP	信用卡｜アコム 消費者金融・カードローン	favicon.ico
acom_jp_card	JP	信用卡｜アコム 消費者金融・カードローン	favicon.ico
amazon_jp	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp_certificate	JP	证件/认证｜Amazon / 本, ファッション, 家電から食品まで / アマゾン	favicon.ico
amazon_jp_custom	JP	定制｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp_noaddress	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp_noaddress_checkdate	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp1	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp2	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_jp3	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp_hq	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp_noaddress	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp_noaddress_checkdate	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp1	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp2	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
amazon_pc_jp3	JP	静态前台｜Amazon.co.jp: ファッション、家電から食品まで / アマゾン	favicon.ico
americanexpress_jp_card	JP	信用卡｜アメリカン・エキスプレス（American Express）公式サイト	favicon.ico
americanexpress_jp_card1	JP	信用卡｜アメリカン・エキスプレス（American Express）公式サイト	favicon.ico
anaco_jp_card	JP	信用卡｜ANA｜フライト予約・空席照会・運航状況はANAのホームページで	favicon.ico
anaco_jp_card1	JP	信用卡｜ANA｜フライト予約・空席照会・運航状況はANAのホームページで	favicon.ico
aplus_jp_card	JP	信用卡｜Aplus（エーピースカード）	favicon.ico
apple_jp	JP	静态前台｜Apple ID	favicon.ico
apple_jp_card	JP	信用卡｜Apple IDを管理	favicon.ico
apple_jp_custom	JP	定制｜Apple ID	favicon.ico
apple_jp_noaddress	JP	静态前台｜Apple ID	favicon.ico
apple_jp_noaddress1	JP	静态前台｜Apple ID	favicon.ico
apple_jp1	JP	静态前台｜Apple ID	favicon.ico
apple_jp2	JP	静态前台｜Apple ID	favicon.ico
apple_jp3	JP	静态前台｜Apple ID	favicon.ico
au_jp_certificate	JP	证件/认证｜au, au PAY, auカード	favicon.ico
au_jp_point	JP	积分/奖励	favicon.ico
auone_jp_bank	JP	银行｜TOP / au ID	favicon.ico
aupay_jp_card	JP	信用卡｜TOP / au ID	favicon.ico
auto_jp_custom	JP	定制	favicon.ico
binance_jp_creditcards	JP	信用卡/券商｜バイナンス - Bitcoin、Ethereum、アルトコインのための暗号資産取引所	favicon.ico
bitflyer_jp_creditcards	JP	信用卡/券商｜bitFlyer（ビットフライヤー） / 暗号資産（仮想通貨）の購入/販売所/取引所	favicon.ico
bybit_jp_creditcards	JP	信用卡/券商｜ビットコイン・イーサリアム・暗号資産（仮想通貨）取引所のBybit（バイビット）	favicon.ico
coin_jp_creditcards	JP	信用卡/券商｜ビットコイン（BTC）・暗号資産（仮想通貨）の取引ならGMOコイン	favicon.ico
daiwa_jp_creditcards	JP	信用卡/券商｜大和証券株式会社	favicon.ico
dmm_jp_card	JP	信用卡	favicon.ico
docomo_jp_bank	JP	银行｜NTTドコモ	favicon.ico
docomo_jp_card	JP	信用卡｜NTTドコモ	favicon.ico
ekinet_jp_card	JP	信用卡｜えきねっと｜JR東日本	favicon.ico
ekinet_jp_card1	JP	信用卡｜えきねっと｜JR東日本	favicon.ico
eplusjp	JP	静态前台	
epos_jp_creditcards	JP	信用卡/券商｜クレジットカードは入会金・年会費永年無料のエポスカード	favicon.ico
eposcard_jp_card	JP	信用卡｜EPOSカード｜クレジットカードはエポスカード	favicon.ico
eposcard_jp_card_checkout	JP	结账｜EPOSカード｜クレジットカードはエポスカード	favicon.ico
eposcard_jp_card_noacount_checkout	JP	结账｜EPOSカード｜クレジットカードはエポスカード	favicon.ico
etax_jp	JP	静态前台｜【e-Tax】国税電子申告・納税システム(イータックス)	favicon.ico
etcmeisai_jp_card	JP	信用卡｜ETCマイレージサービス	favicon.ico
etcmeisai_jp_card1	JP	信用卡｜ETCマイレージサービス	favicon.ico
famidigi_jp_bank	JP	银行｜FamiPay / 株式会社ファミマデジタルワン	favicon.ico
family_jp_card	JP	信用卡｜ファミリーマート	favicon.ico
familyMart_jp_card	JP	信用卡｜ファミリーマート公式ウェブサイト	favicon.ico
fukuokabank_jp_bank	JP	银行｜福岡銀行	favicon.ico
gate_jp_creditcards	JP	信用卡/券商｜ビットコイン、イーサリアム、 3,400+ アルトコインの売買/暗号通貨取引所/Gate.com	favicon.ico
globaljcb_jp_card	JP	信用卡｜JCB Global Site / Credit Cards, Travel, Shopping & More	favicon.ico
gmo_jp_creditcards	JP	信用卡/券商｜GMOクリック証券 - ネット証券（FX・CFD・株・バイナリーオプション）	favicon.ico
gmo_jp_news	JP	公告	favicon.ico
gmoaozora_jp_bank	JP	银行｜GMOあおぞらネット銀行	favicon.ico
gmoaozora_jp_bank1	JP	银行｜GMOあおぞらネット銀行	favicon.ico
interactivebrokers_jp_creditcards	JP	信用卡/券商｜Home / Interactive Brokers LLC	favicon.ico
jabank_jp_bank2	JP	银行｜JAバンク,住宅ローン,マイカーローン,教育ローン,JA貯金,国債,投資信託,資産運用	favicon.ico
jabank_jp_bank3	JP	银行｜JAバンク,住宅ローン,マイカーローン,教育ローン,JA貯金,国債,投資信託,資産運用	favicon.ico
jaccs_jp_card	JP	信用卡｜JACCS（ジャックス）｜クレジット、ローン、分割払い	favicon.ico
jaccs_jp_creditcards	JP	信用卡/券商｜クレジットカードのジャックス	favicon.ico
jal_jp_card	JP	信用卡｜日本航空（JAL） - 国際線・国内線 航空券予約 公式サイト	favicon.ico
jal_jp_card1	JP	信用卡｜日本航空（JAL） - 国際線・国内線 航空券予約 公式サイト	favicon.ico
japanpost_jp_bank	JP	银行｜サイトマップ－ゆうちょ銀行	favicon.ico
japanpost_jp_bank1	JP	银行｜サイトマップ－ゆうちょ銀行	favicon.ico
jcbup_jp_creditcards	JP	信用卡/券商｜クレジットカードなら、JCBカード	favicon.ico
jcbup_jp_creditcards_nocard	JP	信用卡/券商｜クレジットカードなら、JCBカード	favicon.ico
jcbup_jp_creditcards1	JP	信用卡/券商｜クレジットカードなら、JCBカード	favicon.ico
jp_jaccs	JP	静态前台｜T3 Site	
jp_nissenren	JP	静态前台｜T3 Site	
jp_rakuten	JP	静态前台｜ログイン‐楽天	
jp_vandle	JP	静态前台｜jp_vandle	
jppost_jp_card	JP	信用卡｜郵便局のネットショップ｜ギフトから食品、切手・グッズの通販	favicon.ico
jppost_jp_card1	JP	信用卡｜郵便局のネットショップ｜ギフトから食品、切手・グッズの通販	favicon.ico
kuronekoyamato_jp	JP	静态前台｜ヤマト運輸	favicon.ico
kyash_jp_bank	JP	银行｜Kyash - お支払いもお金の管理もかんたんに	favicon.ico
letian_jp_creditcards	JP	信用卡/券商｜楽天市場｜Shopping is Entertainment!	favicon.ico
letian_jp_creditcards1	JP	信用卡/券商｜楽天市場｜Shopping is Entertainment!	favicon.ico
letian_jp_creditcards2	JP	信用卡/券商｜楽天市場｜Shopping is Entertainment!	favicon.ico
lifecard_jp_creditcards	JP	信用卡/券商｜クレジットカードはライフカード	favicon.ico
lifecard_jp_creditcards1	JP	信用卡/券商｜クレジットカードはライフカード	favicon.ico
line_jp_card	JP	信用卡｜LINE｜いつもあなたのそばに。	favicon.ico
mastercard_jp	JP	静态前台｜Mastercard：決済業界におけるグローバルなテクノロジー企業	favicon.ico
match_jp_card	JP	信用卡｜マッチ・ドット・コム（Match.com）｜真剣な出会いを求める人のための婚活・恋愛サイト	favicon.ico
matsui_jp_creditcards	JP	信用卡/券商｜松井証券 - ネット証券/日本株(現物/信用)・米国株・投信・FX・NISAの証券会社	favicon.ico
matsui_jp_news	JP	公告	
mercari_jp_acount_card	JP	信用卡｜メルカリ - 日本最大のフリマサービス	favicon.ico
mercari_jp_noacount_card	JP	信用卡｜メルカリ - 日本最大のフリマサービス	favicon.ico
micard_jp_card	JP	信用卡｜百貨店のクレジットカードなら三越伊勢丹グループのエムアイカード	favicon.ico
micard_jp_card1	JP	信用卡｜百貨店のクレジットカードなら三越伊勢丹グループのエムアイカード	favicon.ico
mizuho_jp_creditcards	JP	信用卡/券商｜みずほ証券	favicon.ico
mizuhobank_jp_bank	JP	银行｜みずほ銀行	favicon.ico
mobit_jp_card	JP	信用卡｜キャッシング、カードローンはSMBCモビット【公式サイト】	favicon.ico
mobitsmb_jp_card	JP	信用卡｜会員専用サービス「Myモビ」について｜お申込み中、ご契約中のお客さま｜SMBCモビット	favicon.ico
monex_jp_creditcards	JP	信用卡/券商｜マネックス証券 / ネット証券（株・アメリカ株・投資信託）	favicon.ico
mufgbkdebit_jp_card	JP	信用卡｜三菱ＵＦＪ銀行	favicon.ico
ncbank_jp_card	JP	信用卡｜西日本シティ銀行｜元気な九州・福岡をさらに元気に	favicon.ico
ncbank_jp_card1	JP	信用卡｜西日本シティ銀行｜元気な九州・福岡をさらに元気に	favicon.ico
nexco_jp_etc	JP	ETC/过路费	favicon.ico
nhk_jp_card	JP	信用卡｜NHK / 日本放送協会	favicon.ico
nintendo_jp_card	JP	信用卡｜任天堂ホームページ	favicon.ico
nissay_jp_card	JP	信用卡｜日本生命保険相互会社	favicon.ico
nissenren_jp_card	JP	信用卡｜株式会社日専連ファイナンス	favicon.ico
nissenrenaomori_jp_card	JP	信用卡｜ウェブサービス「エヌプラネット」	favicon.ico
nomura_jp_creditcards	JP	信用卡/券商	favicon.ico
orico_jp_card	JP	信用卡｜オリコ｜その夢の一歩先へ	favicon.ico
paidy_jp_card	JP	信用卡｜MyPaidy,マイペイディー,まいぺいでぃー	favicon.ico
pairs_jp	JP	静态前台｜Pairs	favicon.ico
paypay_jp	JP	静态前台｜PayPay（ペイペイ）- QRコードで支払うキャッシュレス決済のスマホアプリ	favicon.ico
paypay_jp1	JP	静态前台｜PayPay（ペイペイ）- QRコードで支払うキャッシュレス決済のスマホアプリ	favicon.ico
paypay_jp2	JP	静态前台｜PayPay（ペイペイ）- QRコードで支払うキャッシュレス決済のスマホアプリ	favicon.ico
paypaybank_jp_bank	JP	银行｜PayPay銀行（旧ジャパンネット銀行）	favicon.ico
paypaybank_jp_card	JP	信用卡｜PayPay銀行（旧ジャパンネット銀行）	favicon.ico
pocketcard_jp_card	JP	信用卡｜クレジットカードのお申込みはポケットカード株式会社	favicon.ico
pocketcard_jp_card1	JP	信用卡｜クレジットカードのお申込みはポケットカード株式会社	favicon.ico
rakuten_jp_certificate	JP	证件/认证｜ログイン‐楽天	favicon.ico
rakuten_jp_creditcards	JP	信用卡/券商｜楽天証券株式会社	favicon.ico
rakutencard_jp_card	JP	信用卡｜みずほ銀行	favicon.ico
risona_jp_creditcards	JP	信用卡/券商｜りそな銀行	favicon.ico
risona_jp_creditcards1	JP	信用卡/券商｜りそな銀行	favicon.ico
sagawaExp_jp_card	JP	信用卡｜佐川急便株式会社＜ＳＧホールディングスグループ＞	favicon.ico
saisoncard_jp_card	JP	信用卡｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
saisoncard_jp_card_checkout	JP	结账｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
saisoncard_jp_card1	JP	信用卡｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
saisoncard_jp_card1_checkout	JP	结账｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
saisoncard_jp_card2	JP	信用卡｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
saisoncard_jp_certificate	JP	证件/认证｜クレジットカードは永久不滅ポイントのセゾンカード	favicon.ico
sanjinVpass_jp_creditcards	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sanjinVpass_jp_creditcards1	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sanjinVpass_jp_creditcards2	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sanjinVpass_jp_creditcards3	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sanjinVpass_jp_creditcards4	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sanjinVpass_jp_creditcards5	JP	信用卡/券商｜クレジットカードの三井住友カード	favicon.ico
sbisec_jp_creditcards	JP	信用卡/券商｜SBI証券,SBI,エスビーアイ,ネット証券,証券,株、株式,投資信託,FX,債券,NISA,iDeCo（個人型確定拠出年金）,アプリ,積立、ポイント、キャンペーン	favicon.ico
sbisec_jp_news	JP	公告｜SBI証券,SBI,エスビーアイ,ネット証券,証券,株、株式,投資信託,FX,債券,NISA,iDeCo（個人型確定拠出年金）,アプリ,積立、ポイント、キャンペーン	favicon.ico
scmufg_jp_creditcards	JP	信用卡/券商｜三菱ＵＦＪモルガン・スタンレー証券株式会社	favicon.ico
smartex_jp_card	JP	信用卡｜「スマートEX」気軽にネット予約で新幹線を利用するなら！	favicon.ico
smbc_jp_bank	JP	银行｜三井住友銀行	favicon.ico
smbc_jp_guide	JP	指南｜三井住友銀行	favicon.ico
smbcnikko_jp_creditcards	JP	信用卡/券商｜ログイン / オンライントレード（日興イージートレード） / ＳＭＢＣ日興証券	favicon.ico
suica_jp_card	JP	信用卡｜ビューカードはSuicaを便利に使えるJR東日本グループのクレジットカード	favicon.ico
suica_jp_card1	JP	信用卡｜ビューカードはSuicaを便利に使えるJR東日本グループのクレジットカード	favicon.ico
tepco_jp_card	JP	信用卡｜東京電力｜東京電力グループサイト	favicon.ico
tokyogas_jp_card	JP	信用卡｜myTOKYOGAS / myTOKYOGAS / 東京ガス	favicon.ico
topcard_jp_card	JP	信用卡｜東急カード－電車でもお買物でもポイントが貯まる	favicon.ico
trip_jp_card	JP	信用卡｜トリップドットコム 公式サイト｜航空券・ホテル・列車予約ならTrip.com	favicon.ico
tscubic_jp_card	JP	信用卡｜TS CUBIC WEBサイト	favicon.ico
tscubic_jp_card1	JP	信用卡｜TS CUBIC WEBサイト	favicon.ico
uccardli_jp_card	JP	信用卡｜クレジットカードはUCカード	favicon.ico
uccardli_jp_card1	JP	信用卡｜クレジットカードはUCカード	favicon.ico
ufjup_jp_creditcards	JP	信用卡/券商｜三菱ＵＦＪ銀行	favicon.ico
visa_jp_card	JP	信用卡｜Visa Japan / クレジットカード・デビットカード・プリペイドカード	favicon.ico
vpassne_jp_card	JP	信用卡｜VJA一覧：Welcome to Vpass	favicon.ico
vpassup_jp_creditcards	JP	信用卡/券商｜VJA一覧：Welcome to Vpass	favicon.ico
vpassup_jp_creditcards1	JP	信用卡/券商｜VJA一覧：Welcome to Vpass	favicon.ico
yahoo_jp	JP	静态前台	favicon.ico
yahoo_jp_card	JP	信用卡｜ログイン - Yahoo! JAPAN	favicon.ico
yodobashi_jp_card	JP	信用卡｜ヨドバシ.com - ヨドバシカメラの公式通販サイト【全品無料配達】	favicon.ico
yongwang_jp_creditcards	JP	信用卡/券商｜クレジットカードはイオンカード 暮らしのマネーサイト	favicon.ico
yongwang_jp_creditcards1	JP	信用卡/券商｜クレジットカードはイオンカード 暮らしのマネーサイト	favicon.ico
"""


def _build() -> dict:
    out = {}
    for line in _RAW.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        site, country, description, preview = parts
        if not (SOURCES_DIR / site).is_dir():
            continue
        out[site] = {
            "id": site,
            "name": site,
            "slug": site,
            "filename": site,
            "description": description,
            "country": country,
            "site_url": "",
            "entry": ENTRY,
            "preview": preview if preview and (SOURCES_DIR / site / preview).is_file() else "",
        }
    return out


EXTRA_SOURCES = _build()
