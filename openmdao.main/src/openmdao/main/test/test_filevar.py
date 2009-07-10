"""
Test of FileTraits.
"""

import cPickle
import os
import shutil
import unittest

from enthought.traits.api import Bool, Array, List, Str

from openmdao.main.api import Assembly, Component
from openmdao.main.filevar import FileTrait

# pylint: disable-msg=E1101
# "Instance of <class> has no <attr> member"


class Source(Component):
    """ Produces files. """

    write_files = Bool(True, iostatus='in')
    text_data = Str(iostatus='in')
    binary_data = Array('d', iostatus='in')
    text_file = FileTrait(filename='source.txt', iostatus='out')
    binary_file = FileTrait(filename='source.bin', iostatus='out',
                               binary=True)
        
    def __init__(self, name='Source', *args, **kwargs):
        super(Source, self).__init__(name, *args, **kwargs)

    def execute(self):
        """ Write test data to files. """
        if self.write_files:
            out = open(self.text_file.filename, 'w')
            out.write(self.text_data)
            out.close()

            out = open(self.binary_file.filename, 'wb')
            cPickle.dump(self.binary_data, out, 2)
            out.close()


class Sink(Component):
    """ Consumes files. """

    text_data = Str(iostatus='out')
    binary_data = Array('d', iostatus='out')
    text_file = FileTrait(filename='sink.txt', iostatus='in')
    binary_file = FileTrait(filename='sink.bin', iostatus='in')
        
    def __init__(self, name='Sink', *args, **kwargs):
        super(Sink, self).__init__(name, *args, **kwargs)

    def execute(self):
        """ Read test data from files. """
        inp = open(self.text_file.filename, 'r')
        self.text_data = inp.read()
        inp.close()

        inp = open(self.binary_file.filename, 'rb')
        self.binary_data = cPickle.load(inp)
        inp.close()


class MyModel(Assembly):
    """ Transfer files from producer to consumer. """

    def __init__(self, name='FileVar_TestModel', *args, **kwargs):
        super(MyModel, self).__init__(name, *args, **kwargs)

        Source(parent=self, directory='Source')
        Sink(parent=self, directory='Sink')

        self.connect('Source.text_file', 'Sink.text_file')
        self.connect('Source.binary_file', 'Sink.binary_file')

        self.Source.text_data = 'Hello World!'
        self.Source.binary_data = [3.14159, 2.781828, 42]


class FileTestCase(unittest.TestCase):
    """ Test of FileTraits. """

    def setUp(self):
        """ Called before each test in this class. """
        self.model = MyModel()

    def tearDown(self):
        """ Called after each test in this class. """
        self.model.pre_delete()
        shutil.rmtree('Source')
        shutil.rmtree('Sink')
        self.model = None

    def test_connectivity(self):
        self.assertNotEqual(self.model.Sink.text_data,
                            self.model.Source.text_data)
        self.assertNotEqual(self.model.Sink.binary_data,
                            self.model.Source.binary_data)
        self.assertNotEqual(
            self.model.Sink.binary_file.binary, True)

        self.model.run()

        self.assertEqual(self.model.Sink.text_data,
                         self.model.Source.text_data)
        self.assertEqual(all(self.model.Sink.binary_data==self.model.Source.binary_data),
                         True)
        self.assertEqual(
            self.model.Sink.binary_file.binary, True)

    def test_src_failure(self):
        self.model.Source.write_files = False
        try:
            self.model.run()
        except IOError, exc:
            if str(exc).find('source.txt') < 0:
                self.fail("Wrong message '%s'" % exc)
        else:
            self.fail('IOError expected')

    def test_bad_directory(self):
        try:
            Source(directory='/illegal')
        except ValueError, exc:
            self.assertEqual(str(exc).startswith(
                "Source: Illegal execution directory '/illegal', not a decendant of"),
                True)
        else:
            self.fail('Expected ValueError')

    def test_not_directory(self):
        directory = 'plain_file'
        out = open(directory, 'w')
        out.write('Hello world!\n')
        out.close()

        try:
            self.source = Source(directory=directory)
        except ValueError, exc:
            path = os.path.join(os.getcwd(), directory)
            self.assertEqual(str(exc),
                "Source: Execution directory path '%s' is not a directory."
                % path)
        else:
            self.fail('Expected ValueError')
        finally:
            os.remove(directory)

    def test_bad_new_directory(self):
        self.model.Source.directory = '/illegal'
        try:
            self.model.run()
        except ValueError, exc:
            self.assertEqual(str(exc).startswith(
                "FileVar_TestModel.Source: Illegal directory '/illegal', not a decendant of"),
                True)
        else:
            self.fail('Expected ValueError')


if __name__ == '__main__':
    unittest.main()

