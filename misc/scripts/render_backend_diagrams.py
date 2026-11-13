"""Render jury-facing backend diagrams. Art tools are optional, outside runtime deps.

uv run --with reportlab==5.1.0 --with pymupdf==2.1 python misc/scripts/render_backend_diagrams.py
"""
from pathlib import Path
import argparse
import math
import zipfile

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
W, H = 1920, 1080
C = {'bg':'#F4F5EF','ink':'#123D30','body':'#465D52','muted':'#6D7F74',
     'green':'#22845C','pale':'#E6EFE5','line':'#C9D5C9','white':'#FFFFFF',
     'external':'#F1EADD','warmline':'#D2C1A2','dark':'#183D30','light':'#EDF4E9'}
CV = None
TEXT_BOXES = []


def fill(color):
    CV.setFillColor(HexColor(C.get(color, color)))


def stroke(color):
    CV.setStrokeColor(HexColor(C.get(color, color)))


def rect(x,y,w,h,color='white',edge=None,r=18,lw=1):
    fill(color)
    if edge:stroke(edge)
    CV.setLineWidth(lw)
    CV.roundRect(x,H-y-h,w,h,r,fill=1,stroke=int(edge is not None))


def text(value,x,y,size=22,font='Regular',color='ink',max_width=None):
    width=pdfmetrics.stringWidth(value,font,size)
    if max_width is not None and width>max_width+0.01:
        raise ValueError(f'Text exceeds box ({width:.1f}>{max_width}): {value}')
    if x<0 or x+width>W+1 or y-size<0 or y>H:
        raise ValueError(f'Text outside page: {value}')
    TEXT_BOXES.append((value,x,y,width,size))
    fill(color);CV.setFont(font,size);CV.drawString(x,H-y,value)


def lines(value,x,y,width,size=22,font='Regular',color='body',leading=None):
    leading=leading or size*1.4
    out=[]
    for paragraph in value.split('\n'):
        current=''
        for word in paragraph.split():
            proposal=(current+' '+word).strip()
            if pdfmetrics.stringWidth(proposal,font,size)>width and current:
                out.append(current);current=word
            else:current=proposal
        out.append(current)
    for i,line in enumerate(out):text(line,x,y+i*leading,size,font,color,width)
    return y+len(out)*leading


def tag(value,x,y,width=None,dark=False,size=15):
    width=width or pdfmetrics.stringWidth(value,'Bold',size)+26
    rect(x,y,width,32,'green' if dark else 'pale',r=8)
    text(value,x+13,y+22,size,'Bold','white' if dark else 'green',width-20)


def number(value,x,y):
    fill('green');CV.circle(x,H-y,18,stroke=0,fill=1)
    s=str(value).zfill(2);tw=pdfmetrics.stringWidth(s,'Bold',15)
    text(s,x-tw/2,y+5,15,'Bold','white')


def path(points,color='green',width=2.2,dash=None,arrow=True):
    stroke(color);fill(color);CV.setLineWidth(width)
    CV.setDash(dash or [])
    p=CV.beginPath();p.moveTo(points[0][0],H-points[0][1])
    for x,y in points[1:]:p.lineTo(x,H-y)
    CV.drawPath(p,stroke=1,fill=0);CV.setDash([])
    if arrow:
        (a,b),(x,y)=points[-2:]
        angle=math.atan2(y-b,x-a);length=10;spread=.47
        p=CV.beginPath();p.moveTo(x,H-y)
        for theta in (angle+math.pi-spread,angle+math.pi+spread):
            p.lineTo(x+length*math.cos(theta),H-(y+length*math.sin(theta)))
        p.close();CV.drawPath(p,fill=1,stroke=0)


def page(n,title,subtitle,section):
    CV.bookmarkPage(f'page-{n}')
    CV.addOutlineEntry(f'{n:02d}. {section}',f'page-{n}',level=0)
    CV.linkURL('https://smena-mipt.ru',(88,H-1050,240,H-1025),relative=0,thickness=0)
    fill('bg');CV.rect(0,0,W,H,fill=1,stroke=0)
    tag('СМЕНА',88,45,dark=True)
    text('НАВИГАТОР СОТРУДНИКА',197,68,16,'Bold','muted')
    text(section.upper(),1460,68,16,'Bold','muted',370)
    text(title,88,143,48,'Bold',max_width=1744)
    text(subtitle,88,191,23,'Regular','body',1744)
    path([(88,1012),(1832,1012)],'line',1,arrow=False)
    text('smena-mipt.ru',88,1045,18,'Bold')
    text('Реализованная архитектура • 13.11.2026',660,1045,17,'Regular','muted')
    text(f'{n:02d} / 04',1740,1045,18,'Bold',max_width=92)


def card(x,y,w,h,title,body='',label=None,theme='white',title_size=27,body_size=21):
    rect(x,y,w,h,theme,'warmline' if theme=='external' else 'line',r=18)
    at=y+35
    if label:
        text(label.upper(),x+24,at,14,'Bold','green',w-48);at+=39
    at=lines(title,x+24,at,w-48,title_size,'Bold','ink',title_size*1.15)
    if body:
        end=lines(body,x+24,at+17,w-48,body_size,'Regular','body',body_size*1.45)
        if end-body_size*1.45>y+h-18:
            raise ValueError(f'Text exceeds card height: {title}')


def metric(x,y,w,title,body):
    text(title,x,y,23,'Bold','ink',w)
    lines(body,x,y+31,w,18,'Regular','body',25)


def overview():
    page(1,'Как устроен бэкенд','Документ попадает в общую базу. Вопрос превращается в ответ с открываемыми источниками.','Общий вид')
    rect(370,234,1120,640,'pale','line',r=24)
    text('VPS  /  ЛОКАЛЬНАЯ ОБРАБОТКА',397,268,17,'Bold','green')
    tag('ВНЕШНИЙ API',1552,244,width=202)
    card(88,314,240,210,'Сотрудник','Вопросы\nФайлы и ссылки\nОткрытие цитат',label='Браузер',body_size=20)
    card(410,314,220,210,'Caddy','HTTPS\nПрокси к API',label='На хосте',body_size=20)
    card(690,314,360,210,'FastAPI','Поиск • генерация\nЗагрузка • источники',label='Контейнер API',title_size=33,body_size=22)
    card(1552,314,280,210,'LLM','Command Code\nГенерация по найденным фрагментам',label='По API',theme='external',body_size=20)
    path([(328,413),(410,413)]);text('HTTPS',340,391,14,'Bold','green')
    path([(630,413),(690,413)])
    path([(1050,365),(1552,365)])
    lines('Вопрос + выбранные\nфрагменты источников',1120,314,385,19,'Regular','body',25)
    path([(1552,465),(1050,465)])
    text('Структурированный ответ',1135,494,19,'Regular','body',380)
    card(690,646,360,176,'PostgreSQL + pgvector','Индекс • версии • очередь',label='Контейнер БД',title_size=27,body_size=21)
    card(1120,646,330,176,'Import worker','Чтение • OCR • E5 на CPU',label='Контейнер обработчика',title_size=29,body_size=20)
    path([(850,524),(850,646)])
    text('Поиск и очередь',872,574,17,'Regular','body',195)
    path([(1050,697),(1120,697)]);text('задача',1055,681,13,'Regular','body')
    path([(1120,779),(1050,779)]);text('индекс',1057,805,13,'Regular','body')
    text('Данные на VPS',410,675,23,'Bold',max_width=240)
    lines('Оригиналы файлов и\nартефакты извлечения\nсохраняются на диске.',410,716,236,20,leading=29)
    rect(88,908,1744,76,'white',r=14)
    metric(112,936,480,'Общая база','Документы доступны всем посетителям')
    metric(690,936,500,'E5 работает локально','На VPS не требуется GPU')
    metric(1290,936,510,'Сохраняем источник','Версия, фрагмент и координаты цитаты')
    CV.showPage()


def ingestion():
    page(2,'Как новый документ попадает в поиск','Сохраняем оригинал, обрабатываем документ в фоне и одним переключением публикуем новый снимок индекса.','Загрузка документов')
    tag('ЛОКАЛЬНО: ЧТЕНИЕ, OCR И ЭМБЕДДИНГИ',88,229,width=455)
    text('PDF / DOCX / XLSX  •  до 25 МБ на файл',1265,253,21,'Bold','body',567)
    nodes=[('Принимаем файл','Файл или публичная ссылка\nПроверка формата и размера\nОригинал остаётся на диске'),
           ('Ставим в очередь','Задача в PostgreSQL\nСтатус виден в браузере\nПовтор после сбоя'),
           ('Извлекаем текст','Абзацы, пункты и таблицы\nДля сканов — OCR\nПредупреждения сохраняются'),
           ('Строим векторы','Текст → фрагменты\nmultilingual-e5-small\nТолько новый документ'),
           ('Публикуем индекс','Проверяем снимок базы\nАтомарно меняем указатель\nДокумент доступен всем')]
    for i,(title,body) in enumerate(nodes):
        x=88+i*360
        card(x,326,304,290,title,body,label=f'Этап {i+1}',title_size=26,body_size=20)
        number(i+1,x+25,305)
        if i<4:path([(x+304,461),(x+360,461)])
    text('Что происходит при повторной загрузке',88,672,31,'Bold',max_width=1744)
    card(88,708,544,228,'Идентичные байты','SHA-256 совпал → сообщаем, что файл уже есть. Повторные фрагменты не создаются.',label='Без дублей',title_size=28,body_size=22)
    card(688,708,544,228,'Изменённый файл','Замена одноимённого документа требует разрешения. Старые версии и цитаты сохраняются.',label='Явное обновление',title_size=28,body_size=22)
    card(1288,708,544,228,'Ошибка или предупреждение','Сбой не меняет активный индекс. Неполное извлечение видно как частичный успех.',label='Честный статус',title_size=28,body_size=22)
    text('Обработчик не получает ключ LLM. Эмбеддинги остальных документов используются повторно.',88,979,20,'Regular','body',1744)
    CV.showPage()


def answering():
    page(3,'Как вопрос становится проверяемым ответом','Сначала находим доказательства в базе, затем передаём их модели и открываем источники сотруднику.','Поиск и ответ')
    card(88,283,300,244,'Вопрос сотрудника','Один или несколько вопросов\nНК, КПМ, ГК, «Цифра»',label='Вход',body_size=21)
    card(448,283,320,244,'Разбор вопроса','Разделяем составной запрос\nУчитываем словарь корпусов',label='Подготовка',body_size=21)
    path([(388,386),(448,386)])
    card(830,243,330,145,'По смыслу','E5 → pgvector',label=None,title_size=27,body_size=22)
    card(830,418,330,145,'По словам','Полнотекстовый поиск: русский FTS',label=None,title_size=27,body_size=20)
    path([(768,386),(796,386),(796,308),(830,308)])
    path([(796,386),(796,483),(830,483)])
    card(1230,313,230,193,'RRF','Объединяем\nранги поиска',label='Слияние',title_size=34,body_size=22)
    path([(1160,308),(1198,308),(1198,365),(1230,365)])
    path([(1160,483),(1198,483),(1198,453),(1230,453)])
    card(1520,313,312,193,'Контекст','Фрагменты и соседи\nПункты • таблицы • даты',label='Доказательства',body_size=21)
    path([(1460,408),(1520,408)])
    path([(1676,506),(1676,628)])
    text('Вопрос + контекст',1519,565,19,'Bold','green',313)
    card(1520,628,312,230,'Внешняя LLM','Ответ по источникам\nКратко • шаги • ссылки',label='Через API',theme='external',title_size=28,body_size=22)
    card(1120,628,330,230,'Проверка ответа','JSON-схема\nСуществующие source_id\nУчёт непокрытых частей',label='На сервере',title_size=28,body_size=21)
    path([(1520,742),(1450,742)])
    path([(1120,742),(1000,742)])
    rect(88,628,912,230,'dark',r=20)
    text('Результат для сотрудника',116,673,29,'Bold','white',820)
    lines('Краткий ответ\nПорядок действий\nДокументы и ограничения',116,716,420,23,'Regular','light',35)
    rect(579,690,391,136,'white',r=12)
    tag('ОТКРЫТЬ ИСТОЧНИК',596,706,width=240)
    rect(596,752,356,49,'pale',r=5)
    text('12',606,783,18,'Mono','green')
    text('Подсвеченный фрагмент',643,783,20,'Bold','ink',293)
    text('Версия + блок + точные границы цитаты',88,920,25,'Bold','ink',1600)
    lines('Сервер проверяет структуру и координаты. Смысловую связь вывода с цитатой оценивает модель; OCR может ошибаться.',88,958,1744,20,'Regular','body',28)
    CV.showPage()


def module(x,y,w,path_name,description):
    text(path_name,x,y,19,'Mono','ink',w)
    end=lines(description,x,y+28,w,20,'Regular','body',26)
    return end+23


def modules():
    page(4,'Карта основных модулей','Обязанности модулей. Пути указаны относительно src/navigator/.','Для технической оценки')
    cols=[(88,392,'HTTP и интерфейс','Точки входа'),(536,392,'Обработка файлов','Фоновый процесс'),(984,392,'Поиск','Локальные вычисления'),(1432,400,'Ответ и цитаты','Контракт ответа')]
    for i,(x,w,title,subtitle) in enumerate(cols):
        rect(x,268,w,562,'white','line',r=18)
        number(i+1,x+29,296)
        text(subtitle.upper(),x+58,302,14,'Bold','green',w-78)
        lines(title,x+24,354,w-48,29,'Bold','ink',34)
    y=410
    y=module(112,y,344,'api.py','FastAPI, поиск, ответы и открытие источников')
    y=module(112,y,344,'imports/routes.py','Загрузка файла или публичной ссылки, статус задачи')
    module(112,y,344,'static/index.html','Формы, шаги ответа и подсветка строк')
    y=410
    for name,desc in [('imports/worker.py','Очередь и публикация индекса'),('imports/download.py','Скачивание публичных файлов'),('ingest/pipeline.py','Извлечение в отдельном процессе'),('ingest/extractors.py','PDF, DOCX, XLSX и OCR'),('ingest/chunking.py','Фрагменты с координатами')]:
        y=module(560,y,344,name,desc)
    y=410
    y=module(1008,y,344,'retrieval.py','Составной запрос, слияние выдачи и добор контекста')
    y=module(1008,y,344,'campus.py','Пользовательский словарь сокращений корпусов')
    module(1008,y,344,'ingest/embedding.py','Локальные векторы E5: 384 измерения')
    y=410
    y=module(1456,y,352,'generation.py','Вызов LLM, JSON-схема и существующие ссылки')
    y=module(1456,y,352,'sources.py','Версия, блок, границы цитаты и номера строк')
    lines('Ответ различает:\nподтверждённые сведения,\nчастичный результат,\nнехватку данных, уточнение\nи конфликт.',1456,y,352,20,'Regular','body',28)
    for x,w,_,_ in cols:path([(x+w/2,830),(x+w/2,861)],'green',1.7)
    rect(88,861,1744,96,'pale','line',r=14)
    text('Общее хранилище',112,900,25,'Bold',max_width=390)
    text('ingest/storage.py  +  ingest/schema.sql',520,900,22,'Mono','ink',1270)
    text('PostgreSQL / pgvector: документы, неизменяемые версии, фрагменты, снимки индекса и очередь импорта.',112,936,21,'Regular','body',1696)
    text('Два процесса приложения: API и import-worker. PostgreSQL работает в отдельном контейнере.',88,986,19,'Regular','body',1744)
    CV.showPage()


def main():
    global CV
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir',type=Path,default=Path('/System/Library/Fonts/Supplemental'))
    parser.add_argument('--output',type=Path,default=ROOT/'output')
    args=parser.parse_args()
    for name,file in [('Regular','Arial.ttf'),('Bold','Arial Bold.ttf'),('Mono','Andale Mono.ttf')]:
        path=args.font_dir/file
        if not path.is_file():raise SystemExit(f'Missing font: {path}; provide --font-dir with Arial and Andale Mono fonts')
        pdfmetrics.registerFont(TTFont(name,str(path)))
    pdf_dir=args.output/'pdf';png_dir=args.output/'diagrams'
    pdf_dir.mkdir(parents=True,exist_ok=True);png_dir.mkdir(parents=True,exist_ok=True)
    target=pdf_dir/'smena-backend.pdf'
    CV=canvas.Canvas(str(target),pagesize=(W,H),pageCompression=1)
    CV.setTitle('Смена: архитектура бэкенда')
    CV.setAuthor('Команда проекта Смена')
    CV.setSubject('Реализованная архитектура: загрузка, поиск, генерация и проверяемые цитаты')
    overview();ingestion();answering();modules();CV.save()
    names=['01-system','02-ingestion','03-question-to-answer','04-code-map']
    with pymupdf.open(target) as doc:
        assert len(doc)==4
        for page,name in zip(doc,names,strict=True):
            pix=page.get_pixmap(matrix=pymupdf.Matrix(2,2),alpha=False)
            assert (pix.width,pix.height)==(3840,2160)
            pix.save(png_dir/(name+'.png'))
            thumb=page.get_pixmap(matrix=pymupdf.Matrix(.5,.5),alpha=False)
            thumb.save(png_dir/(name+'-preview.png'))
            assert len(page.get_text())>500
    with zipfile.ZipFile(png_dir/'smena-backend-png-4k.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:archive.write(png_dir/(name+'.png'),name+'.png')
    print(f'Created {target} and four 3840×2160 PNG files; {len(TEXT_BOXES)} text lines checked.')


if __name__=='__main__':main()
