import os
import logging
import datetime
import collections
from pylons import config

import ga_model

#from ga_client import GA

log = logging.getLogger('ckanext.ga-report')

FORMAT_MONTH = '%Y-%m'
MIN_VIEWS = 50
MIN_VISITS = 20

class DownloadAnalytics(object):
    '''Downloads and stores analytics info'''

    def __init__(self, service=None, profile_id=None, delete_first=False):
        self.period = config['ga-report.period']
        self.service = service
        self.profile_id = profile_id
        self.delete_first = delete_first

    def specific_month(self, date):
        import calendar

        first_of_this_month = datetime.datetime(date.year, date.month, 1)
        _, last_day_of_month = calendar.monthrange(int(date.year), int(date.month))
        last_of_this_month =  datetime.datetime(date.year, date.month, last_day_of_month)
        periods = ((date.strftime(FORMAT_MONTH),
                    last_day_of_month,
                    first_of_this_month, last_of_this_month),)
        self.download_and_store(periods)


    def latest(self):
        if self.period == 'monthly':
            # from first of this month to today
            now = datetime.datetime.now()
            first_of_this_month = datetime.datetime(now.year, now.month, 1)
            periods = ((now.strftime(FORMAT_MONTH),
                        now.day,
                        first_of_this_month, now),)
        else:
            raise NotImplementedError
        self.download_and_store(periods)


    def for_date(self, for_date):
        assert isinstance(since_date, datetime.datetime)
        periods = [] # (period_name, period_complete_day, start_date, end_date)
        if self.period == 'monthly':
            first_of_the_months_until_now = []
            year = for_date.year
            month = for_date.month
            now = datetime.datetime.now()
            first_of_this_month = datetime.datetime(now.year, now.month, 1)
            while True:
                first_of_the_month = datetime.datetime(year, month, 1)
                if first_of_the_month == first_of_this_month:
                    periods.append((now.strftime(FORMAT_MONTH),
                                    now.day,
                                    first_of_this_month, now))
                    break
                elif first_of_the_month < first_of_this_month:
                    in_the_next_month = first_of_the_month + datetime.timedelta(40)
                    last_of_the_month = datetime.datetime(in_the_next_month.year,
                                                           in_the_next_month.month, 1)\
                                                           - datetime.timedelta(1)
                    periods.append((now.strftime(FORMAT_MONTH), 0,
                                    first_of_the_month, last_of_the_month))
                else:
                    # first_of_the_month has got to the future somehow
                    break
                month += 1
                if month > 12:
                    year += 1
                    month = 1
        else:
            raise NotImplementedError
        self.download_and_store(periods)

    @staticmethod
    def get_full_period_name(period_name, period_complete_day):
        if period_complete_day:
            return period_name + ' (up to %ith)' % period_complete_day
        else:
            return period_name


    def download_and_store(self, periods):
        for period_name, period_complete_day, start_date, end_date in periods:
            if self.delete_first:
                log.info('Deleting existing Analytics for period "%s"',
                         period_name)
                ga_model.delete(period_name)
            log.info('Downloading Analytics for period "%s" (%s - %s)',
                     self.get_full_period_name(period_name, period_complete_day),
                     start_date.strftime('%Y %m %d'),
                     end_date.strftime('%Y %m %d'))
            data = self.download(start_date, end_date, '~/dataset/[a-z0-9-_]+')
            log.info('Storing Dataset Analytics for period "%s"',
                     self.get_full_period_name(period_name, period_complete_day))
            self.store(period_name, period_complete_day, data, )

            data = self.download(start_date, end_date, '~/publisher/[a-z0-9-_]+')
            log.info('Storing Publisher Analytics for period "%s"',
                     self.get_full_period_name(period_name, period_complete_day))
            self.store(period_name, period_complete_day, data,)

            ga_model.update_publisher_stats(period_name) # about 30 seconds.
            self.sitewide_stats( period_name )

            self.update_social_info(period_name, start_date, end_date)

    def update_social_info(self, period_name, start_date, end_date):
        start_date = start_date.strftime('%Y-%m-%d')
        end_date = end_date.strftime('%Y-%m-%d')
        query = 'ga:hasSocialSourceReferral=~Yes$'
        metrics = 'ga:entrances'
        sort = '-ga:entrances'

        # Supported query params at
        # https://developers.google.com/analytics/devguides/reporting/core/v3/reference
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 filters=query,
                                 start_date=start_date,
                                 metrics=metrics,
                                 sort=sort,
                                 dimensions="ga:landingPagePath,ga:socialNetwork",
                                 max_results=10000,
                                 end_date=end_date).execute()
        data = collections.defaultdict(list)
        rows = results.get('rows',[])
        for row in rows:
            from ga_model import _normalize_url
            data[_normalize_url(row[0])].append( (row[1], int(row[2]),) )
        ga_model.update_social(period_name, data)


    def download(self, start_date, end_date, path='~/dataset/[a-z0-9-_]+'):
        '''Get data from GA for a given time period'''
        start_date = start_date.strftime('%Y-%m-%d')
        end_date = end_date.strftime('%Y-%m-%d')
        query = 'ga:pagePath=%s$' % path
        metrics = 'ga:uniquePageviews, ga:visitors'
        sort = '-ga:uniquePageviews'

        # Supported query params at
        # https://developers.google.com/analytics/devguides/reporting/core/v3/reference
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 filters=query,
                                 start_date=start_date,
                                 metrics=metrics,
                                 sort=sort,
                                 dimensions="ga:pagePath",
                                 max_results=10000,
                                 end_date=end_date).execute()

        if os.getenv('DEBUG'):
            import pprint
            pprint.pprint(results)
            print 'Total results: %s' % results.get('totalResults')

        packages = []
        for entry in results.get('rows'):
            (loc,pageviews,visits) = entry
            packages.append( ('http:/' + loc, pageviews, visits,) ) # Temporary hack
        return dict(url=packages)

    def store(self, period_name, period_complete_day, data):
        if 'url' in data:
            ga_model.update_url_stats(period_name, period_complete_day, data['url'])

    def sitewide_stats(self, period_name):
        import calendar
        year, month = period_name.split('-')
        _, last_day_of_month = calendar.monthrange(int(year), int(month))

        start_date = '%s-01' % period_name
        end_date = '%s-%s' % (period_name, last_day_of_month)
        print 'Sitewide_stats for %s (%s -> %s)' % (period_name, start_date, end_date)

        funcs = ['_totals_stats', '_social_stats', '_os_stats',
                 '_locale_stats', '_browser_stats', '_mobile_stats']
        for f in funcs:
            print ' + Fetching %s stats' % f.split('_')[1]
            getattr(self, f)(start_date, end_date, period_name)

    def _get_results(result_data, f):
        data = {}
        for result in result_data:
            key = f(result)
            data[key] = data.get(key,0) + result[1]
        return data

    def _totals_stats(self, start_date, end_date, period_name):
        """ Fetches distinct totals, total pageviews etc """
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        ga_model.update_sitewide_stats(period_name, "Totals", {'Total page views': result_data[0][0]})

        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:pageviewsPerVisit,ga:bounces,ga:avgTimeOnSite,ga:percentNewVisits,ga:visitors',
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        data = {
            'Pages per visit': result_data[0][0],
            'Bounces': result_data[0][1],
            'Average time on site': result_data[0][2],
            'New visits': result_data[0][3],
            'Total visits': result_data[0][4],
        }
        ga_model.update_sitewide_stats(period_name, "Totals", data)


    def _locale_stats(self, start_date, end_date, period_name):
        """ Fetches stats about language and country """
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 dimensions="ga:language,ga:country",
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        data = {}
        for result in result_data:
            data[result[0]] = data.get(result[0], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Languages", data)

        data = {}
        for result in result_data:
            data[result[1]] = data.get(result[1], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Country", data)


    def _social_stats(self, start_date, end_date, period_name):
        """ Finds out which social sites people are referred from """
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 dimensions="ga:socialNetwork,ga:referralPath",
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        data = {}
        for result in result_data:
            if not result[0] == '(not set)':
                data[result[0]] = data.get(result[0], 0) + int(result[2])
        self._filter_out_long_tail(data, 3)
        ga_model.update_sitewide_stats(period_name, "Social sources", data)


    def _os_stats(self, start_date, end_date, period_name):
        """ Operating system stats """
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 dimensions="ga:operatingSystem,ga:operatingSystemVersion",
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        data = {}
        for result in result_data:
            data[result[0]] = data.get(result[0], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Operating Systems", data)

        data = {}
        for result in result_data:
            if int(result[2]) >= MIN_VIEWS:
                key = "%s %s" % (result[0],result[1])
                data[key] = result[2]
        ga_model.update_sitewide_stats(period_name, "Operating Systems versions", data)


    def _browser_stats(self, start_date, end_date, period_name):
        """ Information about browsers and browser versions """
        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 dimensions="ga:browser,ga:browserVersion",
                                 max_results=10000,
                                 end_date=end_date).execute()
        result_data = results.get('rows')
        # e.g. [u'Firefox', u'19.0', u'20']

        data = {}
        for result in result_data:
            data[result[0]] = data.get(result[0], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Browsers", data)

        data = {}
        for result in result_data:
            key = "%s %s" % (result[0], self._filter_browser_version(result[0], result[1]))
            data[key] = data.get(key, 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Browser versions", data)

    @classmethod
    def _filter_browser_version(cls, browser, version_str):
        '''
        Simplifies a browser version string if it is detailed.
        i.e. groups together Firefox 3.5.1 and 3.5.2 to be just 3.
        This is helpful when viewing stats and good to protect privacy.
        '''
        ver = version_str
        parts = ver.split('.')
        if len(parts) > 1:
            if parts[1][0] == '0':
                ver = parts[0]
            else:
                ver = "%s" % (parts[0])
        # Special case complex version nums
        if browser in ['Safari', 'Android Browser']:
            ver = parts[0]
            if len(ver) > 2:
                num_hidden_digits = len(ver) - 2
                ver = ver[0] + ver[1] + 'X' * num_hidden_digits
        return ver

    def _mobile_stats(self, start_date, end_date, period_name):
        """ Info about mobile devices """

        results = self.service.data().ga().get(
                                 ids='ga:' + self.profile_id,
                                 start_date=start_date,
                                 metrics='ga:uniquePageviews',
                                 sort='-ga:uniquePageviews',
                                 dimensions="ga:mobileDeviceBranding, ga:mobileDeviceInfo",
                                 max_results=10000,
                                 end_date=end_date).execute()

        result_data = results.get('rows')
        data = {}
        for result in result_data:
            data[result[0]] = data.get(result[0], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Mobile brands", data)

        data = {}
        for result in result_data:
            data[result[1]] = data.get(result[1], 0) + int(result[2])
        self._filter_out_long_tail(data, MIN_VIEWS)
        ga_model.update_sitewide_stats(period_name, "Mobile devices", data)

    @classmethod
    def _filter_out_long_tail(cls, data, threshold=10):
        '''
        Given data which is a frequency distribution, filter out
        results which are below a threshold count. This is good to protect
        privacy.
        '''
        for key, value in data.items():
            if value < threshold:
                del data[key]
