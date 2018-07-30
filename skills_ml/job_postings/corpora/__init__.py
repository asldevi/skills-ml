from random import randint
from skills_ml.algorithms.string_cleaners import NLPTransforms
from gensim.models.doc2vec import TaggedDocument
from skills_utils.common import safe_get
import re

class CorpusCreator(object):
    """
        A base class for objects that convert common schema
        job listings into a corpus in documnet level suitable for use by
        machine learning algorithms or specific tasks.

    Example:
    ```python
    from skills_ml.job_postings.common_schema import JobPostingCollectionSample
    from skills_ml.job_postings.corpora.basic import CorpusCreator

    job_postings_generator = JobPostingCollectionSample()

    # Default will include all the cleaned job postings
    corpus = CorpusCreator(job_postings_generator)

    # For getting a the raw job postings without any cleaning
    corpus = CorpusCreator(job_postings_generator, raw=True)
    ```


    Attributes:
        job_posting_generator (generator):  an iterable that generates JSON strings.
                                Each string is expected to represent a job listing
                                conforming to the common schema
                                See sample_job_listing.json for an example of this schema
        document_schema_fields (list): an list of schema fields to be included
        raw (bool): a flag whether to return the raw documents or transformed documents

    Yield:
        (dict): a dictinary only with selected fields as keys and corresponding raw/cleaned value
    """
    def __init__(self, job_posting_generator=None, document_schema_fields=['description','experienceRequirements', 'qualifications', 'skills'],
                 raw=False):
        self.job_posting_generator = job_posting_generator
        self.nlp = NLPTransforms()
        self.raw = raw
        self.document_schema_fields = document_schema_fields
        self.join_spaces = ' '.join
        self.key = ['onet_soc_code']

    @property
    def metadata(self):
        meta_dict = {'corpus_creator': ".".join([self.__module__ , self.__class__.__name__])}
        if self.job_posting_generator:
            meta_dict.update(self.job_posting_generator.metadata)
        return meta_dict

    def _clean(self, document):
        for f in self.document_schema_fields:
            try:
                cleaned = self.nlp.clean_html(document[f]).replace('\n','')
                cleaned = " ".join(cleaned.split())
                document[f] = cleaned
            except KeyError:
                pass
        return document

    def _transform(self, document):
        if self.raw:
            return self._join(document)
        else:
            return self._clean(document)

    def _join(self, document):
        return self.join_spaces([
            document.get(field, '') for field in self.document_schema_fields
        ])

    def __iter__(self):
        for document in self.job_posting_generator:
            document = {key: document[key] for key in self.document_schema_fields}
            yield self._transform(document)


class SimpleCorpusCreator(CorpusCreator):
    """
        An object that transforms job listing documents by picking
        important schema fields and returns them as one large lowercased string
    """
    def _clean(self, document):
        return self.join_spaces([
            self.nlp.lowercase_strip_punc(document.get(field, ''))
            for field in self.document_schema_fields
        ])


class Doc2VecGensimCorpusCreator(CorpusCreator):
    """Corpus for training Gensim Doc2Vec
    An object that transforms job listing documents by picking
    important schema fields and yields them as one large cleaned array of words

    Example:
    ```python

    from skills_ml.job_postings.common_schema import JobPostingCollectionSample
    from skills_ml.job_postings.corpora.basic import Doc2VecGensimCorpusCreator

    job_postings_generator = JobPostingCollectionSample()

    corpus = Doc2VecGensimCorpusCreator(job_postings_generator)

    Attributes:
        job_posting_generator (generator): a job posting generator
        document_schema_fields (list): an list of schema fields to be included
    """
    def __init__(self, job_posting_generator, document_schema_fields=['description','experienceRequirements', 'qualifications', 'skills'], *args, **kwargs):
        super().__init__(job_posting_generator, document_schema_fields, *args, **kwargs)
        self.lookup = {}
        self.k = 0 if not self.lookup else max(self.lookup.keys()) + 1

    def _clean(self, document):
        return self.join_spaces([
            self.nlp.clean_str(document[field])
            for field in self.document_schema_fields
        ])

    def _transform(self, document):
        words = self._clean(document).split()
        tag = [self.k]
        return TaggedDocument(words, tag)

    def __iter__(self):
        for document in self.job_posting_generator:
            self.lookup[self.k] = safe_get(document, *self.key)
            yield self._transform(document)
            self.k += 1


class Word2VecGensimCorpusCreator(CorpusCreator):
    """
        An object that transforms job listing documents by picking
        important schema fields and yields them as one large cleaned array of words
    """
    def __init__(self, job_posting_generator, document_schema_fields=['description','experienceRequirements', 'qualifications', 'skills'], *args, **kwargs):
        super().__init__(job_posting_generator, document_schema_fields, *args, **kwargs)

    def _clean(self, document):
        return self.join_spaces([
            self.nlp.clean_str(document[field])
            for field in self.document_schema_fields
        ])

    def _transform(self, document):
        if self.raw:
            return [self.nlp.word_tokenize(s) for s in self.nlp.sentence_tokenize(self._join(document))]
        else:
            return [self.nlp.word_tokenize(s) for s in self.nlp.sentence_tokenize(self._clean(document))]

    def __iter__(self):
        for document in self.job_posting_generator:
            document = {key: document[key] for key in self.document_schema_fields}
            sentences = self._transform(document)
            for sentence in sentences:
                yield sentence

class JobCategoryCorpusCreator(CorpusCreator):
    """
        An object that extract the label of each job listing document which could be onet soc code or
        occupationalCategory and yields them as a lowercased string
    """
    document_schema_fields = [
        'occupationalCategory']

    def _transform(self, document):
        return self.join_spaces([
            self.nlp.lowercase_strip_punc(document[field])
            for field in self.document_schema_fields
        ])


class SectionExtractCorpusCreator(Doc2VecGensimCorpusCreator):
    """Only return the contents of the configured section headers.

    To work correctly, requires that the original newlines are present.
    Don't bother using if the job postings have already been stripped of newlines.
    """
    def __init__(self, section_regex, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.section_regex = section_regex

    def _transform(self, document):
        words = []
        desclines = document['description'].split('\n')
        prior_empty = False
        heading = ''
        for line in desclines:
            words_in_line = len(line.split(' '))
            if prior_empty and line.strip() and line[0] not in ['+', '*', '-'] and ((words_in_line > 0 and words_in_line < 4) or line.endswith(':')):
                heading = line
            if not line.strip():
                prior_empty = True
            else:
                prior_empty = False
            if re.match(self.section_regex, heading) and line != heading and len(line.strip()) > 0:
                for bullet_char in ['+ ', '* ', '- ']:
                    if line.startswith(bullet_char):
                        line = line.replace(bullet_char, '')
                words.extend(line.split())
        tag = [self.k]
        return TaggedDocument(words, tag)


class RawCorpusCreator(CorpusCreator):
    """
        An object that yields the joined raw string of job posting
    """
    def __init__(self, job_posting_generator, document_schema_fields=['description','experienceRequirements', 'qualifications', 'skills']):
        super().__init__(job_posting_generator, document_schema_fields)

    def _transform(self, document):
        return self.join_spaces([document[field] for field in self.document_schema_fields])
