import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

st.set_page_config(page_title="Vibe Check", page_icon="✨", layout="wide")

SENTIMENT_COLORS = {"liked": "#4ade80", "disliked": "#f87171", "mixed": "#facc15"}
ENERGY_COLORS = {"energizing": "#60a5fa", "draining": "#f97316", "neutral": "#94a3b8"}


def _db_url() -> str:
    url = os.environ["DATABASE_URL"]
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


@st.cache_resource
def get_engine():
    return create_engine(_db_url())


@st.cache_data(ttl=120)
def load_entries() -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT date, activity, sentiment, intensity,
                   energy_effect, category, tags, context
            FROM entries
            ORDER BY date DESC, created_at DESC
            """,
            conn,
            parse_dates=["date"],
        )
    return df


@st.cache_data(ttl=120)
def load_tags() -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql_query(
            "SELECT tag, usage_count FROM tag_vocabulary ORDER BY usage_count DESC LIMIT 40",
            conn,
        )
    return df


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.title("✨ Vibe Check")
st.sidebar.markdown("---")

all_entries = load_entries()

if all_entries.empty:
    st.info("No entries yet — send your bot a voice memo to get started.")
    st.stop()

min_date = all_entries["date"].min().date()
max_date = all_entries["date"].max().date()

date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

sentiment_filter = st.sidebar.multiselect(
    "Sentiment",
    options=["liked", "disliked", "mixed"],
    default=["liked", "disliked", "mixed"],
)

energy_filter = st.sidebar.multiselect(
    "Energy effect",
    options=["energizing", "draining", "neutral"],
    default=["energizing", "draining", "neutral"],
)

categories = sorted(all_entries["category"].dropna().unique())
category_filter = st.sidebar.multiselect("Category", options=categories, default=categories)

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

# Apply filters
start_date, end_date = (date_range[0], date_range[1]) if len(date_range) == 2 else (min_date, max_date)

df = all_entries[
    (all_entries["date"].dt.date >= start_date)
    & (all_entries["date"].dt.date <= end_date)
    & (all_entries["sentiment"].isin(sentiment_filter))
    & (all_entries["energy_effect"].isin(energy_filter))
    & (all_entries["category"].isin(category_filter))
]

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_timeline, tab_patterns, tab_tags = st.tabs(["Timeline", "Patterns", "Tags"])


# ---------------------------------------------------------------------------
# Tab 1: Timeline
# ---------------------------------------------------------------------------

with tab_timeline:
    st.subheader(f"{len(df)} entries")

    search = st.text_input("Search activities and context", placeholder="e.g. meeting, bike, coding")
    if search:
        mask = (
            df["activity"].str.contains(search, case=False, na=False)
            | df["context"].str.contains(search, case=False, na=False)
        )
        df_view = df[mask]
    else:
        df_view = df

    for _, row in df_view.iterrows():
        sentiment_emoji = {"liked": "✅", "disliked": "❌", "mixed": "🔀"}.get(row["sentiment"], "•")
        energy_emoji = {"energizing": "⚡", "draining": "🔋", "neutral": "➖"}.get(row["energy_effect"], "")
        color = SENTIMENT_COLORS.get(row["sentiment"], "#e2e8f0")

        tags_str = " ".join(f"`{t}`" for t in (row["tags"] or []))

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f"{sentiment_emoji}{energy_emoji} **{row['activity']}** &nbsp; "
                    f"<span style='color:gray;font-size:0.85em'>{row['category']} · intensity {row['intensity']}/5</span>",
                    unsafe_allow_html=True,
                )
                if row.get("context"):
                    st.caption(row["context"])
                if tags_str:
                    st.markdown(tags_str)
            with col2:
                st.markdown(
                    f"<div style='text-align:right;color:gray;font-size:0.85em'>{row['date'].strftime('%b %d, %Y')}</div>",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Tab 2: Patterns
# ---------------------------------------------------------------------------

with tab_patterns:
    if df.empty:
        st.info("No data matches your filters.")
        st.stop()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total entries", len(df))
    col2.metric("Liked", len(df[df["sentiment"] == "liked"]))
    col3.metric("Disliked", len(df[df["sentiment"] == "disliked"]))
    col4.metric(
        "Avg intensity",
        f"{df['intensity'].mean():.1f}",
    )

    st.markdown("---")

    # Sentiment trend (weekly)
    st.subheader("Sentiment over time")
    trend = (
        df.copy()
        .assign(week=df["date"].dt.to_period("W").apply(lambda p: p.start_time))
        .groupby(["week", "sentiment"])
        .size()
        .reset_index(name="count")
    )
    fig_trend = px.bar(
        trend,
        x="week",
        y="count",
        color="sentiment",
        color_discrete_map=SENTIMENT_COLORS,
        barmode="stack",
        labels={"week": "", "count": "Entries", "sentiment": "Sentiment"},
    )
    fig_trend.update_layout(margin=dict(t=10, b=10), height=300)
    st.plotly_chart(fig_trend, use_container_width=True)

    col_left, col_right = st.columns(2)

    # Category breakdown
    with col_left:
        st.subheader("By category")
        cat_counts = df.groupby(["category", "sentiment"]).size().reset_index(name="count")
        fig_cat = px.bar(
            cat_counts,
            x="count",
            y="category",
            color="sentiment",
            color_discrete_map=SENTIMENT_COLORS,
            orientation="h",
            labels={"count": "Entries", "category": ""},
        )
        fig_cat.update_layout(margin=dict(t=10, b=10), height=350)
        st.plotly_chart(fig_cat, use_container_width=True)

    # Energy effect breakdown
    with col_right:
        st.subheader("Energy effect")
        energy_counts = df["energy_effect"].value_counts().reset_index()
        energy_counts.columns = ["energy_effect", "count"]
        fig_energy = px.pie(
            energy_counts,
            names="energy_effect",
            values="count",
            color="energy_effect",
            color_discrete_map=ENERGY_COLORS,
            hole=0.4,
        )
        fig_energy.update_layout(margin=dict(t=10, b=10), height=350)
        st.plotly_chart(fig_energy, use_container_width=True)

    # Top liked vs disliked activities
    st.subheader("Most repeated activities")
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Most liked**")
        top_liked = (
            df[df["sentiment"] == "liked"]
            .groupby("activity")
            .agg(count=("activity", "size"), avg_intensity=("intensity", "mean"))
            .sort_values("count", ascending=False)
            .head(10)
            .reset_index()
        )
        st.dataframe(top_liked, hide_index=True, use_container_width=True)

    with col_r:
        st.markdown("**Most disliked**")
        top_disliked = (
            df[df["sentiment"] == "disliked"]
            .groupby("activity")
            .agg(count=("activity", "size"), avg_intensity=("intensity", "mean"))
            .sort_values("count", ascending=False)
            .head(10)
            .reset_index()
        )
        st.dataframe(top_disliked, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 3: Tags
# ---------------------------------------------------------------------------

with tab_tags:
    tags_df = load_tags()

    if tags_df.empty:
        st.info("No tags yet.")
    else:
        st.subheader("Tag frequency")
        fig_tags = px.bar(
            tags_df,
            x="usage_count",
            y="tag",
            orientation="h",
            labels={"usage_count": "Uses", "tag": ""},
            color="usage_count",
            color_continuous_scale="Blues",
        )
        fig_tags.update_layout(
            margin=dict(t=10, b=10),
            height=max(400, len(tags_df) * 22),
            yaxis=dict(autorange="reversed"),
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_tags, use_container_width=True)

        # Tags from filtered entries
        st.subheader("Tags in current filter")
        all_tags = [t for tags in df["tags"] for t in (tags or [])]
        if all_tags:
            tag_counts = pd.Series(all_tags).value_counts().reset_index()
            tag_counts.columns = ["tag", "count"]
            fig_filter_tags = px.bar(
                tag_counts.head(20),
                x="count",
                y="tag",
                orientation="h",
                labels={"count": "Uses", "tag": ""},
                color="count",
                color_continuous_scale="Greens",
            )
            fig_filter_tags.update_layout(
                margin=dict(t=10, b=10),
                height=max(300, len(tag_counts.head(20)) * 22),
                yaxis=dict(autorange="reversed"),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig_filter_tags, use_container_width=True)
        else:
            st.info("No tags in current filter.")
