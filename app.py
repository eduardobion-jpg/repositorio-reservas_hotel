"""
ETAPA 3 - Aplicacao Flask para consultar hoteis, quartos, clientes e reservas.

Antes de executar:
    python gerar_csv.py
    python criar_banco.py

Executar:
    python app.py        (abre na primeira porta livre a partir de 5000)

Rotas:
    /                    Visao geral: linha do tempo das reservas e resumo das tabelas
    /hoteis              Tabela hotel (filtros: estado, nome/cidade)
    /hotel/<hno>         Ficha do hotel, quartos e reservas
    /quartos             Tabela room (filtros: tipo, hotel)
    /clientes            Tabela customer (filtros: estado, nome)
    /cliente/<cno>       Ficha do cliente e historico de reservas
    /reservas            Tabela reservation (filtros: tipo, hotel)
    /reserva/<rno>       Detalhe da reserva, com noites e valor total
"""
import os
import socket
import sqlite3
from datetime import date

from flask import Flask, abort, g, render_template, request
from werkzeug.exceptions import NotFound

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hotel.db")

MOEDA = "US$"  # os hoteis sao dos EUA; troque aqui se quiser outro simbolo
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

# (endpoint, secao do menu, rotulo, tabela no banco)
TABELAS = [
    ("listar_hoteis", "hoteis", "Hotéis", "hotel"),
    ("listar_quartos", "quartos", "Quartos", "room"),
    ("listar_clientes", "clientes", "Clientes", "customer"),
    ("listar_reservas", "reservas", "Reservas", "reservation"),
]

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Banco de dados: uma conexao por requisicao
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row  # acesso as colunas pelo nome
    return g.db


@app.teardown_appcontext
def fechar_db(_erro=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def consultar(sql, params=(), um=False):
    cursor = get_db().execute(sql, params)
    return cursor.fetchone() if um else cursor.fetchall()


def contar(tabela):
    # 'tabela' vem sempre das constantes do programa, nunca do usuario
    return consultar(f"SELECT COUNT(*) AS n FROM {tabela}", um=True)["n"]


def nao_encontrado(mensagem):
    abort(404, description=mensagem)


# ---------------------------------------------------------------------------
# Filtros Jinja2
# ---------------------------------------------------------------------------
@app.template_filter("dinheiro")
def dinheiro(valor):
    """1234.5 -> US$ 1.234,50 (negativos: -US$ 315,40)"""
    if valor is None:
        return "—"
    texto = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if valor < 0 else ''}{MOEDA} {texto}"


@app.template_filter("data_br")
def data_br(valor):
    """'2017-11-13' (ou date) -> 13/11/2017"""
    if valor is None:
        return "—"
    if isinstance(valor, str):
        valor = date.fromisoformat(valor)
    return valor.strftime("%d/%m/%Y")


@app.template_filter("nome_completo")
def nome_completo(cliente):
    """Empresas (title = 'Comp') mostram so o nome; pessoas, titulo + nome + sobrenome."""
    if cliente["title"] == "Comp":
        return cliente["name"]
    partes = (cliente["title"], cliente["firstname"], cliente["name"])
    return " ".join(p for p in partes if p)


# ---------------------------------------------------------------------------
# Menu lateral (disponivel em todos os templates) e pagina de erro
# ---------------------------------------------------------------------------
@app.context_processor
def injetar_menu():
    return {
        "tabelas": [
            {"endpoint": ep, "secao": secao, "rotulo": rotulo, "tabela": tabela,
             "total": contar(tabela)}
            for ep, secao, rotulo, tabela in TABELAS
        ]
    }


@app.errorhandler(404)
def pagina_404(erro):
    mensagem = "Página não encontrada."
    if erro.description != NotFound.description:
        mensagem = erro.description
    return render_template("erro.html", mensagem=mensagem), 404


# ---------------------------------------------------------------------------
# Linha do tempo das reservas (eixo comum a todas as barras)
# ---------------------------------------------------------------------------
def eixo_do_tempo():
    """Calcula o periodo coberto pelas reservas e as marcas de mes do eixo."""
    r = consultar("SELECT MIN(arrival) AS ini, MAX(departure) AS fim FROM reservation", um=True)
    if r["ini"] is None:
        hoje = date.today()
        return {"ini": hoje, "fim": hoje, "dias": 1, "marcas": []}

    ini, fim = date.fromisoformat(r["ini"]), date.fromisoformat(r["fim"])
    dias = max((fim - ini).days, 1)

    ano, mes = ini.year, ini.month
    if ini.day > 1:                      # primeira marca: o mes seguinte ao inicio
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1

    marcas = []
    while date(ano, mes, 1) <= fim:
        dia = date(ano, mes, 1)
        marcas.append({
            "pos": round((dia - ini).days / dias * 100, 2),
            "rotulo": str(ano) if mes == 1 else MESES[mes - 1],  # janeiro mostra o ano
            "ano": mes == 1,
        })
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return {"ini": ini, "fim": fim, "dias": dias, "marcas": marcas}


def posicionar(linhas, eixo):
    """Acrescenta a cada reserva a posicao (esq) e a largura (larg) da barra, em %."""
    saida = []
    for linha in linhas:
        d = dict(linha)
        chegada = date.fromisoformat(d["arrival"])
        saida_dia = date.fromisoformat(d["departure"])
        esq = (chegada - eixo["ini"]).days / eixo["dias"] * 100
        larg = (saida_dia - chegada).days / eixo["dias"] * 100
        d["esq"] = round(esq, 2)
        d["larg"] = round(min(max(larg, 1.2), 100 - esq), 2)
        saida.append(d)
    return saida


# ---------------------------------------------------------------------------
# Visao geral
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    eixo = eixo_do_tempo()
    reservas = posicionar(consultar("SELECT * FROM v_reserva ORDER BY arrival, rno"), eixo)
    colunas = {
        tabela: [c["name"] for c in consultar(f"PRAGMA table_info({tabela})")]
        for _, _, _, tabela in TABELAS
    }
    return render_template("index.html", eixo=eixo, reservas=reservas, colunas=colunas)


# ---------------------------------------------------------------------------
# Hoteis
# ---------------------------------------------------------------------------
@app.route("/hoteis")
def listar_hoteis():
    filtro = {
        "estado": request.args.get("estado", "").strip(),
        "q": request.args.get("q", "").strip(),
    }
    hoteis = consultar(
        """
        SELECT h.hno, h.name, h.city, h.state, h.zip, h.address,
               (SELECT COUNT(*) FROM reservation r WHERE r.hno = h.hno) AS reservas
        FROM hotel h
        WHERE (:estado = '' OR h.state = :estado)
          AND (:q = '' OR h.name LIKE '%' || :q || '%' OR h.city LIKE '%' || :q || '%')
        ORDER BY h.name
        """,
        filtro,
    )
    estados = consultar("SELECT DISTINCT state FROM hotel ORDER BY state")
    return render_template("hoteis.html", hoteis=hoteis, estados=estados,
                           filtro=filtro, total=contar("hotel"))


@app.route("/hotel/<int:hno>")
def detalhe_hotel(hno):
    hotel = consultar("SELECT * FROM hotel WHERE hno = ?", (hno,), um=True)
    if hotel is None:
        nao_encontrado(f"O hotel {hno} não existe.")
    quartos = consultar(
        """
        SELECT rm.roomtype, rm.max_free, rm.price,
               (SELECT COUNT(*) FROM reservation r
                 WHERE r.hno = rm.hno AND r.roomtype = rm.roomtype) AS reservas
        FROM room rm WHERE rm.hno = ? ORDER BY rm.price
        """,
        (hno,),
    )
    reservas = consultar("SELECT * FROM v_reserva WHERE hno = ? ORDER BY arrival", (hno,))
    return render_template("hotel_detalhe.html", hotel=hotel, quartos=quartos, reservas=reservas)


# ---------------------------------------------------------------------------
# Quartos
# ---------------------------------------------------------------------------
@app.route("/quartos")
def listar_quartos():
    filtro = {
        "tipo": request.args.get("tipo", "").strip(),
        "hno": request.args.get("hno", default=0, type=int),
    }
    quartos = consultar(
        """
        SELECT rm.hno, h.name AS hotel, h.city, h.state,
               rm.roomtype, rm.max_free, rm.price,
               (SELECT COUNT(*) FROM reservation r
                 WHERE r.hno = rm.hno AND r.roomtype = rm.roomtype) AS reservas
        FROM room rm
        JOIN hotel h ON h.hno = rm.hno
        WHERE (:tipo = '' OR rm.roomtype = :tipo)
          AND (:hno = 0 OR rm.hno = :hno)
        ORDER BY rm.hno, rm.price
        """,
        filtro,
    )
    tipos = consultar("SELECT DISTINCT roomtype FROM room ORDER BY roomtype")
    hoteis = consultar("SELECT hno, name FROM hotel ORDER BY name")
    return render_template("quartos.html", quartos=quartos, tipos=tipos, hoteis=hoteis,
                           filtro=filtro, total=contar("room"))


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@app.route("/clientes")
def listar_clientes():
    filtro = {
        "estado": request.args.get("estado", "").strip(),
        "q": request.args.get("q", "").strip(),
    }
    clientes = consultar(
        """
        SELECT c.cno, c.title, c.name, c.firstname, c.city, c.state, c.zip, c.account,
               (SELECT COUNT(*) FROM reservation r WHERE r.cno = c.cno) AS reservas
        FROM customer c
        WHERE (:estado = '' OR c.state = :estado)
          AND (:q = '' OR c.name LIKE '%' || :q || '%' OR c.firstname LIKE '%' || :q || '%')
        ORDER BY c.name
        """,
        filtro,
    )
    estados = consultar("SELECT DISTINCT state FROM customer ORDER BY state")
    return render_template("clientes.html", clientes=clientes, estados=estados,
                           filtro=filtro, total=contar("customer"))


@app.route("/cliente/<int:cno>")
def detalhe_cliente(cno):
    cliente = consultar("SELECT * FROM customer WHERE cno = ?", (cno,), um=True)
    if cliente is None:
        nao_encontrado(f"O cliente {cno} não existe.")
    reservas = consultar("SELECT * FROM v_reserva WHERE cno = ? ORDER BY arrival", (cno,))
    return render_template("cliente_detalhe.html", cliente=cliente, reservas=reservas)


# ---------------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------------
@app.route("/reservas")
def listar_reservas():
    filtro = {
        "tipo": request.args.get("tipo", "").strip(),
        "hno": request.args.get("hno", default=0, type=int),
    }
    reservas = consultar(
        """
        SELECT * FROM v_reserva
        WHERE (:tipo = '' OR roomtype = :tipo)
          AND (:hno = 0 OR hno = :hno)
        ORDER BY arrival, rno
        """,
        filtro,
    )
    tipos = consultar("SELECT DISTINCT roomtype FROM room ORDER BY roomtype")
    hoteis = consultar("SELECT hno, name FROM hotel ORDER BY name")
    return render_template("reservas.html", reservas=reservas, tipos=tipos, hoteis=hoteis,
                           filtro=filtro, total=contar("reservation"))


@app.route("/reserva/<int:rno>")
def detalhe_reserva(rno):
    reserva = consultar("SELECT * FROM v_reserva WHERE rno = ?", (rno,), um=True)
    if reserva is None:
        nao_encontrado(f"A reserva {rno} não existe.")
    cliente = consultar("SELECT * FROM customer WHERE cno = ?", (reserva["cno"],), um=True)
    return render_template("reserva_detalhe.html", r=reserva, cliente=cliente)


# ---------------------------------------------------------------------------
# Execucao local (em hospedagem, o servidor WSGI importa 'app' diretamente)
# ---------------------------------------------------------------------------
def porta_livre(host, porta):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, porta)) != 0


def escolher_porta(host="127.0.0.1", porta_inicial=5000):
    porta = porta_inicial
    while not porta_livre(host, porta):
        porta += 1
    return porta


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        raise SystemExit("Banco hotel.db não encontrado. Rode antes: python gerar_csv.py e python criar_banco.py")
    porta = escolher_porta()
    print(f"Servidor em http://127.0.0.1:{porta}")
    app.run(debug=True, port=porta, use_reloader=False)
