"""Paleta e helpers de gráfico Plotly — mesmo padrão visual dos notebooks."""

import plotly.graph_objects as go

AZUL = "#2a78d6"
AQUA = "#1baf7a"
AMARELO = "#eda100"
VERMELHO = "#e34948"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"

_LAYOUT = dict(
    plot_bgcolor=SURFACE,
    paper_bgcolor=SURFACE,
    font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK_2, size=13),
    margin=dict(l=8, r=8, t=44, b=8),
    title=dict(font=dict(color=INK, size=15), x=0),
    hoverlabel=dict(bgcolor="white", font=dict(color=INK)),
)


def barras_h(df, categoria: str, valor: str, titulo: str, cor: str = AZUL,
             fmt_hover: str = ",.0f") -> go.Figure:
    """Barras horizontais, maior no topo, grade só no eixo do valor."""
    d = df.sort_values(valor, ascending=True)
    fig = go.Figure(go.Bar(
        x=d[valor], y=d[categoria], orientation="h",
        marker=dict(color=cor),
        hovertemplate=f"%{{y}}: %{{x:{fmt_hover}}}<extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text=titulo, bargap=0.35, showlegend=False)
    fig.update_xaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK_2))
    return fig


def linha(df, x: str, y: str, titulo: str, cor: str = AZUL,
          fmt_hover: str = ",.0f", sufixo_y: str = "") -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=df[x], y=df[y], mode="lines",
        line=dict(color=cor, width=2),
        hovertemplate=f"%{{x}}: %{{y:{fmt_hover}}}{sufixo_y}<extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text=titulo, showlegend=False)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED))
    return fig


def barras_v(df, x: str, y: str, titulo: str, cor: str = AZUL,
             fmt_hover: str = ",.0f") -> go.Figure:
    fig = go.Figure(go.Bar(
        x=df[x], y=df[y], marker=dict(color=cor),
        hovertemplate=f"%{{x}}: %{{y:{fmt_hover}}}<extra></extra>",
    ))
    fig.update_layout(**_LAYOUT, title_text=titulo, bargap=0.3, showlegend=False)
    fig.update_xaxes(showgrid=False, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont=dict(color=MUTED))
    return fig
