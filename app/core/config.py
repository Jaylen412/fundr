from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SERPAPI_API_KEY: str
    FUNDR_CITYCENTER_LAT: float | None = None
    FUNDR_CITYCENTER_LNG: float | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

settings = Settings()

KNOWN_CHAINS = {
    "starbucks","mcdonald","burger king","wendy","taco bell","subway","chipotle",
    "kfc","panda express","five guys","panera","chick-fil-a","domino","pizza hut",
    "little caesars","olive garden","buffalo wild wings","applebee","ihop","denny",
    "cracker barrel","red lobster","tgi friday","texas roadhouse","outback",
    "jack in the box","arbys","sonic","culver","raising cane","whataburger",
    "wingstop","papa john","dairy queen","jimmy john","jersey mike","a&w",
    "church's chicken","bojangles","shake shack","carls jr","hardee","el pollo loco",
    "waffle house","walmart","target","costco","sams club","home depot","lowe",
    "best buy","walgreens","cvs","rite aid","dollar general","dollar tree","family dollar",
    "kroger","meijer","safeway","whole foods","aldi","trader joe","publix","heb",
    "food lion","giant eagle","winn-dixie","bj's wholesale","macy","nordstrom","tj maxx",
    "marshalls","ross dress for less","kohls","ikea","bed bath & beyond","staples",
    "office depot","office max","gamestop","sears","jcpenney","burlington","petco",
    "petsmart","autozone","oreilly auto parts","advance auto","7-eleven","circle k",
    "shell","bp","chevron","exxon","mobil","valero","speedway","qt","sheetz","casey's",
    "pilot","love's travel stop","ups store","fedex","usps","verizon","att","t-mobile",
    "spectrum","xfinity","comcast","directv","enterprise rent a car","hertz","avis",
    "budget","alamo","national car rental","u-haul","homegoods","bath & body works",
    "victoria's secret","ulta","sephora","foot locker","finish line","nike store",
    "adidas store","old navy","gap","banana republic","h&m","uniqlo","ace hardware",
    "sherwin williams","jiffy lube","valvoline","firestone","goodyear","maaco",
    "meineke","pep boys","midas","h&r block","jackson hewitt","liberty tax","great clips",
    "sport clips","supercuts","massage envy","planet fitness","la fitness","crunch fitness",
    "orangetheory","snap fitness","yoga six"
}
