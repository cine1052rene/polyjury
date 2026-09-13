"""City configurations: where to look for today's definitive public facts."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    id: str
    name: str
    name_local: str
    language: str
    tavily_country: str
    queries: tuple[str, ...]
    domains: tuple[str, ...]
    place_pattern: str

    def is_local(self, text: str) -> bool:
        return bool(re.search(self.place_pattern, text or "", re.I))


LONDON = City(
    id="london",
    name="London",
    name_local="London",
    language="en",
    tavily_country="united kingdom",
    queries=(
        "London tube overground closures this weekend no trains",
        "London station closed all weekend",
        "London road closure event full closure",
        "London museum gallery closed temporarily",
        "London match kick-off time stadium this week",
    ),
    domains=(
        "timeout.com", "standard.co.uk", "bbc.co.uk", "tfl.gov.uk", "mylondon.news",
        "londonworld.com", "theguardian.com", "cityam.com", "visitlondon.com",
        "londonist.com", "skysports.com",
    ),
    place_pattern=(
        r"London|Tube|Overground|Underground|DLR|Elizabeth line|Mildmay|Windrush|Suffragette|Lioness|Weaver|"
        r"Westminster|Camden|Hackney|Islington|Southwark|Lambeth|Kensington|Chelsea|Greenwich|Wembley|"
        r"Stratford|Richmond|Brixton|Soho|Mayfair|Marble Arch|Paddington|Victoria|Waterloo|King's Cross|"
        r"Clapham|Willesden|Wandsworth|Hammersmith|Shoreditch|Canary Wharf"
    ),
)

SEOUL = City(
    id="seoul",
    name="Seoul",
    name_local="서울",
    language="ko",
    tavily_country="south korea",
    queries=(
        "서울 이번 주말 도로 전면 통제 안내",
        "서울 지하철 무정차 통과 운행 중단 예정",
        "서울 임시 휴관 안내 박물관 궁궐",
        "서울 축제 차량 통제 시간 안내",
        "서울 마라톤 대회 교통 통제 구간",
        "잠실 고척 경기 일정 서울",
    ),
    domains=(
        "yna.co.kr", "news.kbs.co.kr", "imnews.imbc.com", "news.sbs.co.kr", "news.jtbc.co.kr",
        "donga.com", "chosun.com", "joongang.co.kr", "hani.co.kr", "khan.co.kr", "seoul.co.kr",
        "newsis.com", "news1.kr", "mk.co.kr", "hankyung.com", "edaily.co.kr", "nocutnews.co.kr",
        "v.daum.net", "n.news.naver.com", "mediahub.seoul.go.kr", "seoul.go.kr",
        "seoulmetro.co.kr", "korail.com",
    ),
    place_pattern=(
        r"서울|Seoul|종로|중구|용산|성동|광진|동대문|중랑|성북|강북|도봉|노원|은평|서대문|마포|양천|강서|"
        r"구로|금천|영등포|동작|관악|서초|강남|송파|강동|잠실|고척|광화문|여의도|홍대|명동|한강|잠수교|반포|"
        r"DDP|경복궁|창덕궁|덕수궁|남산|이태원|성수|북촌|인사동"
    ),
)

CITIES: dict[str, City] = {c.id: c for c in (LONDON, SEOUL)}
