# Import standard library packages
from datetime import date
import os
# Import 3rd party packages
import numpy as np
import pandas as pd
import psycopg2
import streamlit as st
from streamlit_option_menu import option_menu
from sqlalchemy import create_engine

# Setting the wide mode as default for Streamlit
st.set_page_config(layout="wide")

# establish some common date variables
today = date.today()
min_date = date(2022, 1, 1)

# reading in database credentials
user        = st.secrets['postgres']['user']
password    = st.secrets['postgres']['password']
host        = st.secrets['postgres']['host']
port        = st.secrets['postgres']['port']
dbname      = st.secrets['postgres']['dbname']

engine_string = f'postgresql://{user}:{password}@{host}:{port}/{dbname}'

engine = create_engine(engine_string)
conn = psycopg2.connect(**st.secrets["postgres"])
cursor = conn.cursor()

# Retrieve data from database with query below. Needed to change date to a timestamp with 00:00:00. 
sql_code =  (  
"""
    select
         CAST (session_start_time::date as timestamp) as date
        ,session_start_time
        ,session_end_time
        ,Extract(epoch FROM (session_end_time - session_start_time))/60 as duration_min
        ,medium
        ,title
        ,teacher
        ,tags
        ,notes
        ,hyperlink
    from learninglog.history
"""
)

# Using above query retrieve database. Using the 'date' column as the index
learning_log = pd.read_sql(sql_code,engine, index_col='date', parse_dates=True)    

# Creating an empty data frame for days that I don't have data something will still show on any visualizations. 
columns = ['session_start_time','session_end_time','duration_min','medium','title','teacher','tags','notes','hyperlink']
index = pd.date_range(start=min_date, end=today, freq='D')
df = pd.DataFrame(index=index, columns=columns)

# concat DataFrame frame with learning_log DataFrame that actually has data. 
results = pd.concat([df, learning_log], sort=False).sort_index()

# replace NaN values in duration_min column with 0, None for metrics
results.fillna({
    'duration_min': 0,
    'medium':'null',
    'title':'null',
    'teacher': 'null',
    'tags':'null',
    'notes':'null'
}, inplace=True)
# renaming index to look nicer
learning_log.index.name = df.index.name = results.index.name = 'date_index'

# adding a column called date which is the same as index because vega-lite wouldn't let me use index for date field. 
results['date'] = results.index.values

# Shift date by 1 day for some reason vega-lite offsets by 1 day back
results['shifted_date'] = results.date + pd.Timedelta(days=1)

# Navigation bar
selected_page = option_menu(
    menu_title=None,
    options=['Activity','Log a Session'],
    icons=['activity','journal-check'],
    default_index=0,
    orientation='horizontal',
    styles={"container": {"padding": "0px", "width":"25%"}}
)

if selected_page == "Activity":
    # Establishing containers 
    header = st.container()
    metrics = st.container()
    heat_map = st.container()
    learning_sessions = st.expander('Learning Sessions')

    # Defining side bar features
    with st.sidebar:
        st.header("Filters") 
        # Start and end dates
        start_date = st.date_input("Start Date",
                                        value = min_date,
                                        min_value = min_date, 
                                        max_value = today)
        end_date = st.date_input("End Date",
                                        value = today,
                                        min_value = min_date, 
                                        max_value = today)
        # Multi Selector for medium
        sorted_unique_medium = sorted(results.medium.unique())
        selected_medium = st.multiselect('Medium', sorted_unique_medium, sorted_unique_medium)
        # Multi Selector for title
        sorted_unique_title = sorted(results.title.unique())
        selected_title = st.multiselect('Title', sorted_unique_title, sorted_unique_title)
        # Multi Selector for teacher
        sorted_unique_teacher= sorted(results.teacher.unique())
        selected_teacher = st.multiselect('Teacher/Author', sorted_unique_teacher, sorted_unique_teacher)
        # Multi Selector for tags. Going to be more work because there can be multiple tags in one row
        tags = ';'.join(results['tags'])
        sorted_unique_tags = list(set(tags.split(sep=';')))
        sorted_unique_tags.sort()
        selected_tags = st.multiselect('Tags', sorted_unique_tags, sorted_unique_tags) 

    #filtered results
    results_filtered_by_date = results.loc[start_date:end_date]


    filt =  (results_filtered_by_date.medium.isin(selected_medium)) & \
            (results_filtered_by_date.title.isin(selected_title))   & \
            (results_filtered_by_date.teacher.isin(selected_teacher)) & \
            (results_filtered_by_date.tags.str.split(';', expand=True).isin(map(str,selected_tags)).any(axis=1))

    results_filtered = results_filtered_by_date[filt]    

    # Defining Header Elements
    with header:
        st.title("Learning log 🧠")
        st.text("Keep updated with what I have been learning about! Inspired by Github's contribution graph.")

    # Defining metric Elements
    with metrics:
        c1, c2, c3, c4 = st.columns((5,2,2,6))
        
        # Calculating time studied metric
        def minutes_to_hours(duration_min):
            total_hours_studied = int(total_duration_min//60)
            total_minutes_studied = int(total_duration_min % 60)
            return f"{total_hours_studied} Hours {total_minutes_studied} Minutes"
        total_duration_min = results_filtered[start_date : end_date].loc[:,'duration_min'].sum()
        c1.metric('Total Time Logged Learning ⏱️', minutes_to_hours(total_duration_min))
        
        # Calculate learning day streaks metric
        def streaks(df, col):
            sign = np.sign(df[col])
            s = sign.groupby((sign!=sign.shift()).cumsum()).cumsum()
            return df.assign(u_streak=s.where(s>0, 0.0), d_streak=s.where(s<0, 0.0).abs())
        # Need to group learning sessions by day
        group_results = pd.DataFrame(results_filtered['duration_min']).resample('D').sum()
        # Using streaks function defined above. Stole from https://stackoverflow.com/questions/42397647/pythonic-way-to-calculate-streaks-in-pandas-dataframe 
        streak = streaks(group_results, 'duration_min')
        # Taking the most recent streak unless streak is 0 for today then take yesterday streak
        if int(streak['u_streak'].iloc[-1]) == 0 and streak.index[-1].date() == today:
            learning_streak = int(streak['u_streak'].iloc[-2])
        else:
            learning_streak = int(streak['u_streak'].iloc[-1])
        c2.metric('Current Streak 🔥',str(learning_streak) + ' Days')

        # Defining max streak
        max_learning_streak = int(streak['u_streak'].max())
        c3.metric('Max Streak 🔥',str(max_learning_streak) + ' Days')
    
    with heat_map:
        group_by_shifted_day = (results_filtered  
                                .set_index(results_filtered['shifted_date'])
                                .loc[:,'duration_min']
                                .resample('D')
                                .sum()
                                .reset_index()
        )
        group_by_shifted_day['date_column'] = pd.to_datetime(group_by_shifted_day['shifted_date']).dt.date
        st.vega_lite_chart(group_by_shifted_day,{
        "mark": {"type": "rect"},
        "encoding": {
            "x": {
            "field": "shifted_date",
            "type": "ordinal",
            "timeUnit": "week",
            "title": '',
            "axis": {"tickBand": "extent"}
            },
            "y": {
            "field": "shifted_date",
            "type": "ordinal",
            "timeUnit": "day",
            "title": '',
            "axis": {"tickBand": "extent"}
            },
            "color": {
            "field": "duration_min",
            "type": "quantitative",
            "aggregate": "sum",
            "legend": True,
            "scale": {"scheme": "greens"}
            },
            "tooltip": [
                {"field": "date_column", "type": "temporal"},
                {"field": "duration_min","type": "quantitative","aggregate": "sum"}
            ]
        },
        "width": 1000,
        "height": 250,
        "autosize": {"type": "fit", "contains": "padding"},
        "config": {
            "background": "#0e1117",
            "axis": {
            "labelColor": "#fafafa",
            "titleColor": "#fafafa",
            "grid": True,
            "gridwidth": 100,
            "gridColor": "#0e1117",
            "labelFont": "\"Source Sans Pro\", sans-serif",
            "titleFont": "\"Source Sans Pro\", sans-serif",
            "labelFontSize": 12,
            "titleFontSize": 12
            },
            "legend": {
            "labelColor": "#fafafa",
            "titleColor": "#fafafa",
            "labelFont": "\"Source Sans Pro\", sans-serif",
            "titleFont": "\"Source Sans Pro\", sans-serif",
            "labelFontSize": 12,
            "titleFontSize": 12
            },
            "title": {
            "color": "#fafafa",
            "subtitleColor": "#fafafa",
            "labelFont": "\"Source Sans Pro\", sans-serif",
            "titleFont": "\"Source Sans Pro\", sans-serif",
            "labelFontSize": 12,
            "titleFontSize": 12
            }
        },
        "padding": {"bottom": 20}
        })

    with learning_sessions:
        not_null_mask = results_filtered['duration_min'].gt(0)
        st.dataframe(results_filtered
                        .loc[not_null_mask, :]
                        .sort_values(by='session_start_time', ascending=False)
                    )

if selected_page == "Log a Session":
    header = st.container()
    action_container = st.container()
    text = st.container()
    with header:
        c1,c2 = st.columns((4,8))
        c2.title("Log a learning session! 📝")
    with st.form('session_logger'):
        with action_container:
            c2, c3, c4, c5, c6, c7, c8, c9, c10 = st.columns((1,1,1,1,1,1,1,1,1))
            session_date = c2.date_input("Date",
                                            value = today,
                                            max_value = today
            )
            session_start_time = c3.time_input('Start Time')
            session_end_time = c4.time_input('End Time')
            medium = c5.text_input('Medium')
            topic = c6.text_input('Topic')
            title = c7.text_input('Title')
            teacher = c8.text_input('Teacher/Author')
            hyperlink = c9.text_input('Resource URL')
            tags = c10.text_input('Tags ; separated')
        with text:
            notes = st.text_area('Description about what you learned about.')
        submit = st.form_submit_button('Log!')
    
    def submit_routine(submit):
        if submit:
            try:
                with open("crud_password.txt") as f:
                    lines = f.readlines()
                    password = lines[0].strip()
            except:
                st.error("❌ You don't have the necessary credentials to use this form")
                return
            if password == os.getenv('crud_password'):
                sql_code = (
                    "INSERT INTO learninglog.history( "
                        "session_start_time, "
                        "session_end_time, "
                        "medium, "
                        "title, "
                        "teacher, "
                        "topic, "
                        "hyperlink, "
                        "tags, "
                        "notes) "
                    "VALUES ( "
                        f"'{str(session_date) + ' ' + str(session_start_time)}',"
                        f"'{str(session_date) + ' ' + str(session_end_time)}',"
                        f"'{str(medium)}',"
                        f"'{str(title)}',"
                        f"'{str(teacher)}',"
                        f"'{str(topic)}',"
                        f"'{str(hyperlink)}',"
                        f"'{str(tags)}',"
                        f"'{str(notes)}'"
                    ");"
                )
                cursor.execute(sql_code)
                conn.commit()
                st.success("Added session to learning log 🥳")
            else:
                st.error("❌ You don't have the necessary credentials to make entries")
                return
    submit_routine(submit)
