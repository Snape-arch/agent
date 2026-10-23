"""Conservative literal consistency; never claims semantic entailment.

Arabic numerals, common ML magnitude suffixes, percentages and multipliers are
compared only with the cited fragments. Derived results and other number systems
still require review; a matching numeral does not prove its metric or relation.
"""
from decimal import Decimal,DecimalException,localcontext
import re
import unicodedata

_QUANTITY=re.compile(
    r'(?<![A-Za-z0-9_.])(?P<number>[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?)'
    r'\s*(?P<scale>billion\b|million\b|thousand\b|[BMK](?![A-Za-z])|万|亿)?'
    r'\s*(?P<unit>%|percent(?:age)?\b|times\b|[x×](?![A-Za-z])|倍)?',re.I)
_SCALES={'billion':'1e9','b':'1e9','million':'1e6','m':'1e6','thousand':'1e3','k':'1e3','万':'1e4','亿':'1e8'}


def _quantities(text):
    text=unicodedata.normalize('NFKC',str(text or ''))
    text=re.sub(r'百分之\s*(\d+(?:\.\d+)?)',r'\1%',text)
    results=[]
    for match in _QUANTITY.finditer(text):
        number=match['number'].replace(',','');surface=match.group().strip()
        try:
            if len(number)>64:raise ValueError('unbounded numeral')
            with localcontext() as context:
                context.prec=64;context.Emax=100;context.Emin=-100
                literal=Decimal(number)
                if literal and not -100<=literal.adjusted()<=100:
                    raise ValueError('quantity exponent outside audit bounds')
                value=literal*Decimal(_SCALES.get((match['scale'] or '').lower(),'1'))
                canonical=str(value.normalize()) if value else '0'
            unit=(match['unit'] or '').lower()
            unit='percent' if unit in ('%','percent','percentage') else 'multiplier' if unit else ''
            results.append((surface,canonical,unit))
        except (DecimalException,ValueError):results.append((surface,None,None))
    return results


def audit_numeric_support(text,cited_fragments):
    evidence={(value,unit) for fragment in cited_fragments for _,value,unit in _quantities(fragment) if value is not None}
    quantities=_quantities(text);unmatched=[]
    for surface,value,unit in quantities:
        if value is None or (value,unit) not in evidence and (unit or not any(v==value for v,_ in evidence)):
            if surface not in unmatched:unmatched.append(surface)
    return dict(scope='arabic_literals_common_ml_scales',quantities_checked=len(quantities),
                unsupported_quantities=unmatched,review_required=bool(unmatched),semantic_entailment_verified=False)
