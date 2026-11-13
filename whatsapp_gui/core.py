import csv
import random
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Contact:
    phone: str
    name: str


def normalize_phone(value):
    # Only strip whitespace and ordinary telephone punctuation; never discard letters.
    number = re.sub(r'[\s()+.\-/]', '', value)
    if not number.isascii() or not number.isdigit():
        raise ValueError('telefone contém caracteres inválidos')
    if len(number) in (10, 11):
        number = '55' + number
    elif len(number) not in (12, 13) or not number.startswith('55'):
        raise ValueError('esperado número brasileiro nacional ou com 55 completo')
    if number == '5511999999999':
        return None
    return number


def read_contacts(path):
    contacts, errors, seen = [], [], set()
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        sample = stream.read(8192)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(stream, dialect=dialect)
        if not {'phone', 'name'}.issubset(reader.fieldnames or []):
            raise ValueError('CSV precisa das colunas phone e name')
        for line, row in enumerate(reader, 2):
            raw = (row.get('phone') or '').strip()
            if not raw:
                continue
            try:
                phone = normalize_phone(raw)
            except ValueError as exc:
                errors.append(f'Linha {line}: {exc}')
                continue
            if phone is None or phone in seen:
                continue
            seen.add(phone)
            name = (row.get('name') or '').strip() or f'Contato {random.SystemRandom().randint(100000, 999999)}'
            contacts.append(Contact(phone, name))
    return contacts, errors


def wait_seconds(base, rng=random):
    if base < 0:
        raise ValueError('tempo base não pode ser negativo')
    return base + rng.randint(60, 180)
