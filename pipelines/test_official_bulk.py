import unittest
from pipelines.official_bulk import numeric_range, source_chain_names, metric_line, line_match_stats

class OfficialBulkMatchingTests(unittest.TestCase):
    def test_vietnamese_numeric_cells_preserve_ranges(self):
        self.assertEqual(numeric_range('4 - 4,5'),[4,4.5])
        self.assertEqual(numeric_range('2,5'),[2.5,2.5])
        self.assertIsNone(numeric_range('QHCT'))
        self.assertIsNone(numeric_range('-2'))

    def test_explicit_child_alley_does_not_fall_back_to_parent(self):
        names=source_chain_names({'name':'Hẻm 39/16','route':'Hẻm 39 - cuối','context_road':''})
        self.assertEqual(names,[])
        names=source_chain_names({'name':'Hẻm số 949','route':'Nguyễn Duy Trinh - nhà số 949/4A','context_road':''})
        self.assertEqual(names,['Hẻm 949 Nguyễn Duy Trinh'])

    def test_crossing_source_cannot_pass_alignment(self):
        way=metric_line([[106.76,10.82],[106.7602,10.82]])
        crossing=metric_line([[106.7601,10.8199],[106.7601,10.8201]])
        self.assertEqual(line_match_stats(way,crossing)['aligned_fraction'],0)
        self.assertEqual(line_match_stats(way,way)['aligned_fraction'],1)

if __name__=='__main__':unittest.main()
