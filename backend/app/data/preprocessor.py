import pandas as pd


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Clean và validate DataFrame trước khi truyền cho Analysis Agent."""

    if df.empty:
        print("DataFrame rỗng, không có gì để preprocess.")
        return df

    # Chỉ giữ đúng 5 cột theo contract
    df = df[["review_id", "business_id", "stars", "text", "date"]].copy()

    # Drop rows thiếu dữ liệu quan trọng
    df = df.dropna(subset=["review_id", "business_id", "text"])

    # Đảm bảo đúng kiểu dữ liệu
    df["stars"] = df["stars"].astype(int).clip(1, 5)
    df["date"]  = pd.to_datetime(df["date"])
    df["text"]  = df["text"].str.strip()

    # Drop reviews rỗng sau khi strip
    df = df[df["text"].str.len() > 0]

    # Drop duplicates
    df = df.drop_duplicates(subset=["review_id"])

    df = df.reset_index(drop=True)
    return df