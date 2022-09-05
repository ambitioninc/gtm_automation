import io
import streamlit as st
# from streamlit import caching
import gtmarket as gtm
import pandas as pd
import numpy as np
import fleming
import datetime
import copy
import locale
locale.setlocale(locale.LC_ALL, 'en_US')
import easier as ezr
from dateutil.relativedelta import relativedelta
from gtmarket.predictor import spread_values
import holoviews as hv
import itertools
hv.extension('bokeh')
from holoviews import opts
opts.defaults(opts.Area(width=800, height=400), tools=[])
opts.defaults(opts.Curve(width=800, height=400, tools=['hover']))



USE_PG=True

def get_when():
    return fleming.floor(datetime.datetime.now(), hour=1)

def display(hv_obj):
    st.write(hv.render(hv_obj, backend='bokeh'))

def float_to_dollars(val):
    return locale.currency(val, grouping=True).split('.')[0]


def to_dollars(ser):
    return [float_to_dollars(x) for x in ser]

def to_percent(ser):
    return ['-' if x == '-' else f'{x}%' for x in ser]

@st.cache
def convert_dataframe(df):
    return df.to_csv().encode('utf-8')


def plot_frame(df, alpha=1, use_label=True, units='', include_total=True, ylabel='ACV'):  # pragma: no cover
    import holoviews as hv
    colorcycle = itertools.cycle(ezr.cc.codes)
    c_list = []
    base = 0 * df.iloc[:, -1]
    for col in df.columns:
        if use_label:
            final = df[col].iloc[-1]
            label = col
            label = label.split('_')[0].title()
            label = f'{label} {final:0.1f}{units.upper()}'
            if include_total and (col == df.columns[-1]):
                label = label + f'  Total={df.iloc[-1].sum():0.1f}{units.upper()}'
        else:
            label = ''
        y = df[col]
        c = hv.Area(
            (df.index, y + base, base),
            kdims=['Date'],
            vdims=[f'{ylabel} ${units.upper()}', 'base'],
            label=label
        ).options(alpha=alpha, color=next(colorcycle), show_grid=True)
        c_list.append(c)
        c_list.append(hv.Curve((df.index, y + base)).options(color='black', alpha=.01))
        base += y
    return hv.Overlay(c_list).options(legend_position='top')


class BlobPrinter():
    def __init__(self):
        self.ps = gtm.PipeStats()
        self.ps.disable_pickle_cache()

        # ################
        self.ps.enable_pickle_cache()
        # ################
    
    @ezr.cached_container
    def _blob(self):
        
        mph = gtm.ModelParamsHist(use_pg=USE_PG)
        pm = mph.get_latest()
        blob = pm.to_blob()
        return blob
    
    @ezr.cached_container
    def blob(self):
        blob = self._blob
        for key in [
            'existing_pipe_model_with_expansion',            
            'existing_pipe_model']:
            blob.pop(key)
        return blob


    def get_frames(self):
        ps = self.ps
        # return self.ps.get_opp_timeseries('num_sals', interval_days=30)
        ser_sal2sql = (100 * ps.get_conversion_timeseries('sal2sql_opps', interval_days=90, bake_days=30)).round(1).iloc[-1]
        ser_sql2win = (100 * ps.get_conversion_timeseries('sql2won_opps', interval_days=365, bake_days=90)).round(1).iloc[-1]
        ser_sal2win = (100 * ps.get_conversion_timeseries('sal2won_opps', interval_days=365, bake_days=90)).round(1).iloc[-1]
        
        ser = ps.get_opp_timeseries('num_sals', interval_days=30).iloc[-1, :]
        ser['total'] = ser.sum()
        dfs = pd.DataFrame({'SALS / month': ser}).round().astype(int)
        
        
        dfd = (pd.DataFrame({'ACV': ps.get_mean_deal_size_timeseries().iloc[-1, :]})).round(1)
        dfd = dfd.loc[['enterprise', 'commercial', 'velocity'], :]
        
        
        dfwr = pd.DataFrame({
            'SAL⮕SQL': ser_sal2sql,
            'SQL⮕WON': ser_sql2win,
            'SAL⮕WON': ser_sal2win,
        })
        
        ser = (100 * ps.get_stage_win_rates_timeseries(interval_days=365, bake_days=90).iloc[-1, :]).round(1)
        ser = ser[['SAL', 'Discovery', 'Demo', 'Proposal', 'Negotiation']]
        dfswr = pd.DataFrame({'Win rate by stage': ser})        
        
        today = fleming.floor(datetime.datetime.now(), day=1)
        dfo = ps.op.df_orders
        dfo.loc[:, 'market_segment'] = [ezr.slugify(m) for m in dfo.market_segment]

        dfo = dfo[(dfo.order_start_date <= today) & (dfo.order_ends > today)]
        ser = (12 * dfo.groupby(by='market_segment')[['mrr']].sum()).round(2).mrr
        ser = ser[['commercial', 'enterprise', 'velocity']]
        ser['combined'] = ser.sum()
        dfr = pd.DataFrame({'Current ARR': ser})
        
        dfn = ps.op.get_ndr_metrics()
        dfn = dfn[dfn.variable.isin(['ndr', 'renewed_pct', 'expanded_pct'])].set_index(['market_segment', 'variable'])[['value']].unstack('variable')
        dfn.columns = dfn.columns.get_level_values(1)
        dfn = dfn.rename(columns={
            'ndr': '12-month NDR',
            'renewed_pct': '12-month Gross Retention',
            'expanded_pct': '12-month Expansion',
            })
        dfn = dfn.loc[
            ['commercial', 'enterprise', 'velocity', 'combined'],
            ['12-month Gross Retention', '12-month Expansion',  '12-month NDR']
        ].round(1)
        
        dft = ps.get_conversion_timeseries('sal2won_time', interval_days=365, bake_days=90).iloc[[-1], :].round().astype(int).T
        dft.columns = ['Days to Win']
        dft.index.name = None      
        
        df_sales = dfs
        df_sales = df_sales.join(dfwr).drop('total')
        df_sales = df_sales.join(dft)
        df_sales = df_sales.join(dfd)
        sal_val = (.01 * df_sales['SAL⮕WON'] * df_sales['ACV']).round().astype(int)
        sql_val = (.01 * df_sales['SQL⮕WON'] * df_sales['ACV']).round().astype(int)
        value_rate = sal_val * df_sales['SALS / month']
        
        
        df_sales['SAL Val'] = to_dollars(sal_val)
        df_sales['SQL Val'] = to_dollars(sql_val) #[locale.currency(x, grouping=True).split('.')[0] for x in sql_val]
        df_sales.loc[:, 'ACV'] = to_dollars(df_sales.ACV) #[locale.currency(x, grouping=True).split('.')[0] for x in df_sales.ACV]
        df_sales.loc[:, 'SAL Value / Month'] = to_dollars(value_rate) #[locale.currency(x, grouping=True).split('.')[0] for x in value_rate]
        
        for col in dfwr.columns:
            df_sales.loc[:, col] = to_percent(df_sales.loc[:, col])
        
        
        df_arr = dfr
        df_arr = df_arr.join(dfn)
        df_arr = df_arr.fillna('-')
        monthly_rate = (.01 * df_arr['12-month NDR']) ** (1 / 12) - 1
        # display(df_arr)
        df_arr['Value / Month'] = df_arr['Current ARR'] * monthly_rate
        
        df_arr.loc[:, 'Current ARR'] = to_dollars(df_arr['Current ARR'])
        df_arr.loc[:, '12-month Gross Retention'] = to_percent(df_arr.loc[:, '12-month Gross Retention'])
        df_arr.loc[:, '12-month Expansion'] = to_percent(df_arr.loc[:, '12-month Expansion'])
        df_arr.loc[:, '12-month NDR'] = to_percent(df_arr.loc[:, '12-month NDR'])
        df_arr.loc[:, 'Value / Month'] = to_dollars(df_arr['Value / Month'])
        df_arr.index.name = None

        dfswr.loc[:, 'Win rate by stage'] = to_percent(dfswr.loc[:, 'Win rate by stage'])

        return df_sales, dfswr, df_arr


# class MiniModelCache:
#     def __init__(self, sqlite_file='/tmp/minimodel_cache.sqlite', use_pg=False, stale_seconds=3600):
#         if use_pg:
#             self.mm = ezr.MiniModelSqlite(file_name=sqlite_file, overwrite=False, read_only=False)
#         else:
#             self.mm = ezr.MiniModelPG(overwrite=False, read_only=False)
#         self.stale_seconds = stale_seconds

#         self.functions = {}

#     def set_last_run(self):
#         df = pd.DataFrame([{'time': datetime.datetime.now()}])
#         self.mm.create('mm_cache_last_run', df)

#     def get_last_run(self):
#         if 'mm_cache_last_run' in self.mm.table_names:
#             return self.mm.tables.mm_cache_last_run.df.time.iloc[0]
#         else:
#             return datetime.datetime(2000, 1, 1)

#     @property
#     def needs_rerun(self):
#         now = datetime.datetime.now()
#         last_run = self.get_last_run()
#         elapsed_seconds = (now - last_run).total_seconds()
#         return elapsed_seconds > self.stale_seconds

#     def register(self, name, func):
#         self.functions[name] = func

#     def recompute(self):
#         for name, func in self.functions.items():
#             df = func()
#             self.mm.create(name, df)
#         self.set_last_run()

#     def get(self, name):
#         if self.needs_rerun:
#             self.recompute()
    
#         if name not in self.mm.table_names:
#             func = self.functions[name]
#             df = func()
#             self.mm.create(name, df)
#             self.set_last_run()

#         return getattr(self.mm.tables, name).df



"""
OKAY.  I'M RUNNING OUT OF STEAM HERE.


I'M TRYING TO FIGURE OUT IF THIS MINIMODELCACHE ABSRACTION IS ANY GOOD FOR MY
STREAMLIT FUNCTIONS.

THE BASIC IDEA IS TO ADD ANOTHER LAYER OF CACHING.
STREAMLIT HAS A REALLY FAST CACHE
THEN THERE IS A DATABASE CACHE OF RESULTS THAT CAN MAYBE BE REFRESHED ON A CRON JOB
THAT WAY WHEN STREAMLIT IS RUN, IT'LL ALWAYS PULL FROM THE DB CACHE
AND DATA CAN HAVE UP TO SAY AN HOUR LATENCY
"""

    

def _get_forecast_frames():
    bp = BlobPrinter()
    return bp.get_frames()



@st.cache
def get_forecast_frames(when):
    """
    when is only used to invalidate cache
    """
    mmc = MiniModelCache()
    mmc.register('get_forecast_frames', _get_forecast_frames)
    bp = BlobPrinter()
    return bp.get_frames()



# @st.cache
# def get_forecast_frames(when):
#     """
#     when is only used to invalidate cache
#     """
#     bp = BlobPrinter()
#     return bp.get_frames()


@st.cache
def get_sales_progress_frames(when):
    today = fleming.floor(datetime.datetime.now(), day=1)
    tomorrow = today + relativedelta(days=1)
    ending_exclusive = '1/1/2023'
    since = '1/1/2022'

    pg = PredictorGetter()

    dfw, dff, _ = pg.get_plot_frames(since=since, today=today, ending_exclusive=ending_exclusive, units='m')
    # dff = pg.get_predicted_revenue(starting=tomorrow, ending_exclusive=ending_exclusive)
    # dfw = pg.get_won_revenue(starting=since, ending_inclusive=today)

    # dfw, dff = pp._get_plot_frames(since='1/1/2022', today='6/23/2022', ending_exclusive='1/1/2023', units='m')
    # dff.hvplot()
    dfx = pd.DataFrame({
        'won': dfw.iloc[-1],
        'remaining': dff.iloc[-1],
    }).T
    dfx['total'] = dfx.sum(axis=1)
    dfx = dfx.T
    dfx['total'] = dfx.sum(axis=1)
    dfx.columns.name = '2022 sales'
    dfx = dfx.round().astype(int)
    dfxd = dfx.copy()
    for col in dfx.columns:
        dfx.loc[:, col] = to_dollars(dfx.loc[:, col])
    return dfx, dfxd

def get_prediction_history(when):
    today = fleming.floor(datetime.datetime.now(), day=1)
    ending_exclusive = '1/1/2023'
    since = '1/1/2022'

    pg = PredictorGetter()

    dfh = pg.get_prediction_history(since=since, ending_exclusive=ending_exclusive,  units='m')
    return dfh


class PredictorGetter:
    def __init__(self, pipe_stats_obj=None, include_sales_expansion=True):
        if pipe_stats_obj is None:
            pipe_stats_obj = gtm.PipeStats()
        self.ps = pipe_stats_obj
        self.include_sales_expansion = include_sales_expansion
        self.mph = gtm.ModelParamsHist(use_pg=USE_PG)
        
    def get_predicted_revenue(self, starting=None, ending_exclusive=None):
        if starting is None:
            starting = datetime.datetime.now()
            
        starting = pd.Timestamp(starting)
        starting = fleming.floor(starting, day=1)        
        if ending_exclusive is None:
            ending_exclusive = starting + relativedelta(years=1)
        ending_exclusive = pd.Timestamp(ending_exclusive)
        deals = gtm.Deals(
            starting=starting,
            ending_exclusive=ending_exclusive,
            include_sales_expansion=self.include_sales_expansion,
            use_pg=USE_PG,
            model_params_hist=self.mph,

        )
        return deals.df_predicted
    
    @ezr.cached_container
    def _df_won(self):
        ps = gtm.PipeStats(pilots_are_new_biz=True, sales_expansion_are_new_biz=self.include_sales_expansion)
        df = ps.get_opp_timeseries(value='deal_acv', cumulative_since='12/31/2020')
        return df
        
    def get_won_revenue(self, starting=None, ending_inclusive=None):
        today = fleming.floor(datetime.datetime.now(), day=1)
        if ending_inclusive is None:
            ending_inclusive = today
        if starting is None:
            starting = fleming.floor(today, year=1)
        starting = pd.Timestamp(starting)
        ending_inclusive = pd.Timestamp(ending_inclusive)
        if starting < pd.Timestamp('1/1/2020'):
            raise ValueError('Can only get revenue since 1/1/2020')
        
        df = self._df_won
        df = df.loc[starting - relativedelta(days=1):ending_inclusive, :].sort_index()
        df = df - df.iloc[0, :]
        df = df.loc[starting:ending_inclusive, :]
        ind = pd.date_range(starting, ending_inclusive)
        df = df.reindex(index=ind)
        df = df.fillna(method='ffill')
        return df
    
    def get_forecast(self, since=None, today=None, ending_exclusive=None, separate_past_future=False):
        if today is None:
            today = fleming.floor(datetime.datetime.now(), day=1)
        if since is None:
            since = fleming.floor(today, year=1)
        if ending_exclusive is None:
            ending_exclusive = today + relativedelta(years=1)
            
        since, today, ending_exclusive = map(pd.Timestamp, [since, today, ending_exclusive])
        tomorrow = today + relativedelta(days=1)
            
        
        dfw = self.get_won_revenue(starting=since, ending_inclusive=today)
        dff = self.get_predicted_revenue(starting=tomorrow, ending_exclusive=ending_exclusive)
        dff = dff + dfw.iloc[-1, :]
        
        dfw = dfw.loc[since:ending_exclusive, :]
        dff = dff.loc[since:ending_exclusive, :]
        
        if separate_past_future:
            return dfw, dff
        else:
            df = pd.concat([dfw, dff], axis=0)
            return df

    @ezr.cached_container
    def df_model_param_history(self):
        mph = gtm.ModelParamsHist(use_pg=USE_PG)
        df = mph.get_history()
        return df
        
    def get_prediction_history(self, since=None, ending_exclusive=None,  units='m'):
        # mph = gtm.ModelParamsHist(use_pg=USE_PG)
        # df = mph.get_history()
        df = self.df_model_param_history
        min_time, max_time = [fleming.floor(d, day=1) for d in [df.time.min(), df.time.max()]]
        
        dates = pd.date_range(min_time, max_time)
        predictions = []
        for today in dates:
            dfw, dff = self.get_plot_frames_for_span(since=since, today=today, ending_exclusive=ending_exclusive, units=units)
            predictions.append(dff.iloc[-1, :].sum())
            
        dfp = pd.DataFrame({'acv': predictions}, index=dates)
        ind = pd.date_range(dfp.index[0], ending_exclusive, inclusive='left')
        dfp = dfp.reindex(ind).fillna(method='ffill')
        return dfp

    def get_plot_frames_for_span(self, since=None, today=None, ending_exclusive=None, units='m'):
        units = units.lower()
            
        units_lookup = {
            'k': 1000,
            'm': 1e6,
            'u': 1,
        }
        
        scale = units_lookup[units]
        
        dfw, dff = self.get_forecast(since=since, today=today, ending_exclusive=ending_exclusive, separate_past_future=True)
        if not dff.empty:
            dfft = dff.T
            dfft.loc[:, dfw.index[-1]] = dfw.iloc[-1, :]
            dff = dfft.T.sort_index()
        
        dff = dff / scale
        dfw = dfw /  scale

        # dfh = self.get_prediction_history(since=since, ending_exclusive=ending_exclusive, units=units)
        return dfw, dff#, dfh

    
    def get_plot_frames(self, since=None, today=None, ending_exclusive=None, units='m'):
        units_lookup = {
            'k': 1000,
            'm': 1e6,
            'u': 1,
        }
        scale = units_lookup[units]
        dfw, dff = self.get_forecast(since=since, today=today, ending_exclusive=ending_exclusive, separate_past_future=True)
        dff = dff / scale
        dfw = dfw / scale
        dfh = self.get_prediction_history(since=since, ending_exclusive=ending_exclusive, units=units)
        return dfw, dff, dfh



class NDRGetter:
    def __init__(self):
        self.op = gtm.OrderProducts()
        self.ps = gtm.PipeStats()
        
    def _get_metrics(self, now, months=12):
        """
        Returns comparison metrics for the state of orders "now" compared to "months" ago
        """
        df = self.op.get_ndr_metrics(months=months, now=now)
        df.insert(0, 'date', now)
        
        return df


    
    @ezr.cached_container
    def df_metrics(self):
        dates = pd.date_range('1/1/2021', datetime.datetime.now())

        df_list = []
        for date in dates:
            df_list.append(self._get_metrics(date, months=12))

        df = pd.concat(df_list, axis=0, ignore_index=True, sort=False)
        return df


@st.cache
def get_ndr_metrics(when):
    return NDRGetter().df_metrics


class CSExpansion:
    def __init__(self, today=None, ending_exclusive=None):
        self.ps = gtm.PipeStats()
        if today is None:
            today = fleming.floor(datetime.datetime.now(), day=1)
        self.today = pd.Timestamp(today)
        if ending_exclusive is None:
            ending_exclusive = self.today + relativedelta(years=1)
            
        self.ending = pd.Timestamp(ending_exclusive) - relativedelta(days=1)
        
    @ezr.cached_container
    def expansion_rate(self):
        # This gets the average expansion rate for existing contracted mrr
        # dfx = get_ndr_metrics(get_when())
        dfx = NDRGetter().df_metrics
        dfx = dfx[dfx.variable == 'expanded_pct']
        dfx = dfx.pivot(index='date', columns='market_segment', values='value')
        then = fleming.floor(datetime.datetime.now(), day=1) - relativedelta(years=1)
        dfx = dfx.loc[then:, :].drop('combined', axis=1)
        exp_ser = .01 * dfx.mean()
        return exp_ser   
    
    @ezr.cached_container
    def df_cs_expansion(self):
        df = self.ps.loader.df_all
        df = df[df.created_date >= '1/1/2021']
        df = df[df.type == 'CS Expansion']
        return df
    
    @ezr.cached_container
    def df_cs_expansion_open(self):
        df = self.df_cs_expansion
        df = df[df.status_code == 0]
        df = df[df.acv.notnull()]
        
        # Ignore stuff with close dates in the past
        last_week = self.today - relativedelta(weeks=1)
        df = df[df.close_date >= last_week]
        
        # If the opp was opened after "today", I shouldn't know about it
        df = df[df.created_date <= self.today]
        
        # 90% of all won expansion opps closed within 90 days, so ignore opps set to close a long time from opening
        df['expected_days_open'] = (df.close_date - df.created_date).dt.days
        df = df[df.expected_days_open <= 90]
        
        return df
    
    @ezr.cached_container
    def win_rate(self):
        # Get the win rate of cs expansion opps
        df = self.df_cs_expansion
        df = df[df.status_code != 0]
        dfx = df.copy()
        df = df.groupby(by=['market_segment', 'status_code'])[['opportunity_id']].count().unstack('status_code')
        df.columns = df.columns.get_level_values(1)
        df['win_rate'] = df.loc[:, 2] / df.sum(axis=1)
        ser_win_rate = df.win_rate
        return ser_win_rate
    
    @ezr.cached_container
    def expanding_account_set(self):
        df = self.df_cs_expansion_open
        accounts = df.account_id.drop_duplicates()
        return set(accounts)
    
    @ezr.cached_container
    def df_cs_expansion_expected_from_pipe(self):
        df = self.df_cs_expansion_open
        df = df[['opportunity_name', 'market_segment', 'close_date', 'acv', 'expected_days_open', 'stage']]
        df['discounted_acv'] = df.market_segment.map(self.win_rate) * df.acv
        
        df = df.groupby(by=['close_date', 'market_segment'])[['discounted_acv']].sum().unstack('market_segment').fillna(0)
        df.columns = df.columns.get_level_values(1)
        return df
    
    @ezr.cached_container
    def df_cs_expansion_from_current_orders(self):
        dfo = self.ps.op.df_orders
        dfo = dfo[['account_id', 'order_start_date', 'market_segment', 'mrr']]
        
        # Ignore contributions for accounts with open axpansion opps
        dfo = dfo[~dfo.account_id.isin(self.expanding_account_set)]
        
        dfo['acv'] = 12 * dfo.mrr


        dfo = dfo.groupby(by=['order_start_date', 'market_segment'])[['acv']].sum().unstack('market_segment').fillna(0)
        dfo.columns = [ezr.slugify(c) for c in dfo.columns.get_level_values(1)]

        starting, ending = dfo.index[0], self.ending
        dates = pd.date_range(starting, ending, name='date')

        # Note that in spreading the values of a year, I'm only including first year sales expansion
        # estimates.  Everything else gets accounted for in NDR
        dfo = dfo.reindex(dates).fillna(0)
        for col in dfo.columns:
            dfo.loc[:, col] = spread_values(dfo.loc[:, col] * self.expansion_rate[col], 1 * 365)

        dfo = dfo.loc[self.today:, :].cumsum()    
        return dfo
    
    @ezr.cached_container
    def df_cs_expansion_forecast(self):
        dfo = self.df_cs_expansion_from_current_orders
        dfp = self.df_cs_expansion_expected_from_pipe
        dfp = dfp.reindex(dfo.columns, axis=1).fillna(0)
        dfp = dfp.reindex(dfo.index).fillna(0)
        dfp = dfp.cumsum()
        
        dfo = dfo + dfp
        return dfo
    

@st.cache
def get_cs_expansion_metrics(when, today=None, ending_exclusive=None):
    return CSExpansion(today=today, ending_exclusive=ending_exclusive).df_cs_expansion_forecast
    

class ARRGetter:
    def __init__(self, starting=None, ending_exclusive=None):
        # Get a reference for today
        self.today = fleming.floor(datetime.datetime.now(), day=1)
        self.ps = gtm.PipeStats()

        if starting is None:
            starting = fleming.floor(self.today, year=1)
        self.starting = starting
        
        if ending_exclusive is None:
            ending_exclusive = self.starting + relativedelta(years=1)
        self.ending_exclusive = pd.Timestamp(ending_exclusive)
        self.ending_inclusive = self.ending_exclusive - relativedelta(days=1)
        self.mph = gtm.ModelParamsHist(use_pg=USE_PG)
        
        
        # self.csx = CSExpansion(self.today, ending_exclusive=ending_exclusive)
        
    def _get_new_biz_frame(self, today, ending_exclusive):
        deals = gtm.Deals(
            starting=today,
            ending_exclusive=self.ending_exclusive,
            include_sales_expansion=True,
            use_pg=USE_PG,
            model_params_hist=self.mph
        )
        return deals.df_predicted
        
    @ezr.cached_container
    def df_new_biz(self):
        return self._get_new_biz_frame(today=self.today, ending_exclusive=self.ending_exclusive)
        
    def get_arr_history_frame(self, today=None):
        if today is None:
            today = self.today
        today = pd.Timestamp(today)
        
        # Use the cs plotter to get average of last 30 days of NDR
        # dfm = self.cs_plotter.df_metrics
        # dfm = get_ndr_metrics(get_when())
        dfm = NDRGetter().df_metrics
        
        
        # Based on yearly NDR, compute an exponential time constant for each segment
        dfm = dfm[dfm.variable == 'ndr']
        dfm = .01 * dfm.pivot(index='date', columns='market_segment', values='value')
        tau = dfm.iloc[-30:, :].mean()
        tau = -365 / np.log(tau)

        # Get the orderproducts frame
        # dfo = self.cs_plotter.op.df_orders
        dfo = self.ps.op.df_orders
        dfo.loc[:, 'market_segment'] = [ezr.slugify(m) for m in dfo.market_segment]
        
        # Make a range of dates from starting till today
        dates = pd.date_range(self.starting, today)
        
        # Populate each day with the amount of ARR on that day
        rec_list = []
        for date in dates:
            rec = {'date': date}
            batch = dfo[(dfo.order_start_date<=date) & (dfo.order_ends > date)]
            rec.update((12 * batch.groupby(by='market_segment').mrr.sum()).to_dict())
            rec_list.append(rec)

        # Make a frame out of the ARR
        df = pd.DataFrame(rec_list)
        df = df.set_index('date')
        
        # Extend the frame one year out into the future
        df = df.reindex(pd.date_range(self.starting, self.ending_inclusive, name='date')).fillna(method='ffill').reset_index()
        
        # Compute how many days into the future each day corresponds to
        df['days'] = np.maximum(0, (df.date - today).dt.days)
        segments = [c for c in df.columns if c not in ['days', 'date']]

        # Discount the current ARR into the future using the NDR for each segment
        for segment in segments:
            df.loc[:, segment] = df.loc[:, segment] * np.exp(-df.days / tau[segment])

        # Get rid of cols I don't want
        df = df.drop('days', axis=1)
        df = df.set_index('date')
        return df

    @ezr.cached_container
    def df_arr_history(self):
        return self.get_arr_history_frame()
    
    
    def get_prediction_history_frame(self):
        
        rec_list = []
        for date in pd.date_range('6/2/2022', self.today):
            dfc = self.get_arr_history_frame(today=date)
            deals = gtm.Deals(
                starting=date,
                ending_exclusive=self.ending_exclusive,
                include_sales_expansion=True,
                use_pg=USE_PG,
            )
            dfp = deals.df_predicted
            # It's important you create a fresh csx here, so that it's anchored to date
            csx = CSExpansion(self.ps, self.cs_plotter, date, ending_exclusive=self.ending_exclusive)
            dfx = csx.df_cs_expansion_forecast
            
            
            current_arr = dfc.loc[self.ending_inclusive, :]
            rec = current_arr
                
            rec = rec + dfp.loc[self.ending_inclusive, :]
            rec = rec + dfx.loc[self.ending_inclusive, :]
            rec['date'] = date
            
            rec_list.append(rec)
            
        dfh =  pd.DataFrame(rec_list).set_index('date').sort_index()
        dfh = pd.DataFrame({'arr': dfh.sum(axis=1)})
        return dfh
        
    @ezr.cached_container
    def df(self):
        # import pdb; pdb.set_trace()
        dfc = self.df_arr_history
        dfn = self.df_new_biz
        dfn = dfn.reindex(dfc.index).fillna(0)
        

        dfx = CSExpansion(today=self.today, ending_exclusive=self.ending_exclusive).df_cs_expansion_forecast
        dfx = dfx.loc[dfx.index[0]:dfx.index[-1]]
        dfx = dfx.reindex(dfc.index).fillna(0)
        
        df = dfn + dfc + dfx
        return df

@st.cache
def get_arr_timeseries(when, starting=None, ending_exclusive=None):
    return ARRGetter(starting=starting, ending_exclusive=ending_exclusive).df



class DashData:
    def __init__(self, use_pg=False):
        sqlite_file='/tmp/dash_play.sqlite'
        if use_pg:
            1/0
            self.mm = ezr.MiniModelPG(overwrite=False, read_only=False)
        else:
            self.mm = ezr.MiniModelSqlite(file_name=sqlite_file, overwrite=False, read_only=False)

        self.methods = [
            'process_arr_time_series',
            'process_sales_progress',
            'process_sales_timeseries',
            'process_process_stats',
        ]

    def run(self):
        for method in self.methods:
            getattr(self, method)()

    def _save_frame(self, name, df, save_index=True):
        if save_index:
            df = df.reset_index(drop=False)
        data = df.to_csv(index=False)
        date = fleming.floor(datetime.datetime.now(), day=1)
        dfs = pd.DataFrame([{'date': date, 'data': data}])
        self.mm.upsert(name, ['date'], dfs)

    def process_arr_time_series(self):
        df =  ARRGetter(starting=None, ending_exclusive=None).df
        print(df.head().to_string())
        self._save_frame('arr_time_series', df)

    def process_sales_progress(self):
        today = fleming.floor(datetime.datetime.now(), day=1)
        ending_exclusive = '1/1/2023'
        since = '1/1/2022'

        pg = PredictorGetter()

        dfw, dff, _ = pg.get_plot_frames(since=since, today=today, ending_exclusive=ending_exclusive, units='u')
        dfx = pd.DataFrame({
            'won': dfw.iloc[-1],
            'remaining': dff.iloc[-1],
        }).T
        dfx['total'] = dfx.sum(axis=1)
        dfx = dfx.T
        dfx['total'] = dfx.sum(axis=1)
        dfx.columns.name = '2022 sales'

        dfx = dfx.round()

        self._save_frame('sales_progress', dfx)

    def process_sales_timeseries(self):
        pg = PredictorGetter()
        df_won, df_forecast, df_pred_hist = pg.get_plot_frames(since='1/1/2022', ending_exclusive='1/1/2023', units='u')
        self._save_frame('sales_won_timeseries', df_won)
        self._save_frame('sales_forecast_timeseries', df_forecast)
        self._save_frame('sales_prediction_history', df_pred_hist)

    def process_process_stats(self):
        bp = BlobPrinter()
        df_sales, df_stage_win_rate, df_arr = bp.get_frames()

        self._save_frame('sales_stats', df_sales)
        self._save_frame('sales_stats_stage_win_rate', df_stage_win_rate)
        self._save_frame('sales_stats_arr', df_arr)




    def process_arr_timeseries(self):
        pass


    def get_latest(self, name):
        if name not in self.mm.table_names:
            raise ValueError(f'{name} not in {self.mm.table_names}')

        df = self.mm.query(f"""
        SELECT
            data
        FROM
            {name}
        ORDER BY 
            date DESC
        LIMIT 1
        """)
        data = df.data.iloc[0]
        dfo = pd.read_csv(io.StringIO(data))
        return dfo




# #######################################3
# df = get_arr_timeseries(get_when()) / 1e6
# dfprog, dfprod_download =  get_sales_progress_frames(get_when())        
# df_sales, df_stage_wr, df_arr = get_forecast_frames(get_when())
# dfw, dff, dfh = get_plotting_frames(when)

