import React, { useState, useEffect } from 'react';
import api from '../services/api';

const PlacementTestComponent = ({ onClose, onComplete }) => {
  const [questions, setQuestions] = useState([]);
  const [testId, setTestId] = useState(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [answers, setAnswers] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    let isMounted = true;
    api.getPlacementTest()
      .then(data => {
        if (isMounted) {
          if (data.questions && data.test_id) {
            setQuestions(data.questions);
            setTestId(data.test_id);
          } else {
            setQuestions(data);
          }
          setLoading(false);
        }
      })
      .catch(err => {
        if (isMounted) {
          console.error(err);
          setLoading(false);
        }
      });
    return () => {
      isMounted = false;
    };
  }, []);

  const handleOptionSelect = (questionId, optionIndex) => {
    setAnswers(prev => ({
      ...prev,
      [questionId]: optionIndex
    }));
  };

  const handleNext = () => {
    if (currentStep < questions.length - 1) {
      setCurrentStep(prev => prev + 1);
    } else {
      handleSubmit();
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const response = await api.submitPlacementTest(answers, testId);
      setResult(response);
      if (onComplete) {
        onComplete();
      }
    } catch (error) {
      console.error("Submission failed", error);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-slate-900 bg-opacity-95 flex items-center justify-center z-50">
        <div className="bg-slate-800 p-8 rounded-xl max-w-md w-full text-center border border-slate-700">
          <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-indigo-500 mx-auto mb-4"></div>
          <h2 className="text-2xl font-bold text-white mb-4">題目生成中...</h2>
          <p className="text-slate-300">AI 正在根據知識圖譜為您量身打造測驗題目，請稍候。</p>
        </div>
      </div>
    );
  }

  if (result) {
    return (
      <div className="fixed inset-0 bg-slate-900/95 flex items-center justify-center z-50">
        <div className="bg-slate-800 p-8 rounded-xl max-w-md w-full text-center border border-slate-700 animate-fade-in">
          <div className="text-6xl mb-4">🚀</div>
          <h2 className="text-2xl font-bold text-white mb-4">測驗完成！</h2>
          <div className="mb-6 space-y-2">
             <p className="text-xl text-white font-bold">
               答對 {result.correct_count} / {result.total_count} 題
             </p>
             <p className="text-slate-300">
               {result.message}
             </p>
             <p className="text-slate-400 text-sm">
               (共解鎖 <span className="text-indigo-400 font-bold">{result.unlocked_nodes.length}</span> 個單元)
             </p>
          </div>
          <button 
            onClick={onClose}
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold transition-colors shadow-[0_4px_0_0_#3730a3]"
          >
            開始學習旅程
          </button>
        </div>
      </div>
    );
  }

  if (questions.length === 0) {
    return (
      <div className="fixed inset-0 bg-slate-900/95 flex items-center justify-center z-50">
        <div className="bg-slate-800 p-8 rounded-xl max-w-md w-full text-center border border-slate-700">
          <h2 className="text-2xl font-bold text-white mb-4">目前沒有測驗</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white">關閉</button>
        </div>
      </div>
    );
  }

  const currentQuestion = questions[currentStep];
  const progress = ((currentStep + 1) / questions.length) * 100;

  return (
    <div className="fixed inset-0 bg-slate-900 z-50 flex flex-col">
      {/* Header */}
      <div className="p-4 flex items-center justify-between border-b border-slate-800 bg-slate-900">
        <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
        <div className="flex-1 mx-4">
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <div 
              className="h-full bg-indigo-500 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
        <div className="text-slate-400 font-mono text-sm">
          {currentStep + 1}/{questions.length}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 max-w-2xl mx-auto w-full">
        <div className="mb-8 text-center">
          <span className="inline-block px-3 py-1 bg-indigo-900/50 text-indigo-300 rounded-full text-sm font-bold mb-4 border border-indigo-800">
            快速通關測驗
          </span>
          <h2 className="text-2xl font-bold text-white leading-relaxed">
            {currentQuestion.question}
          </h2>
          
          {currentQuestion.debugInfo && (
            <div className="mt-4 p-3 bg-red-900/30 border border-red-500/50 rounded-lg text-left text-sm inline-block max-w-lg">
              <div className="text-red-400 font-bold mb-1 text-xs uppercase tracking-wider">[Debug Info]</div>
              <div className="text-slate-300 mb-1">
                <span className="text-slate-500 font-mono mr-2">ANS:</span>
                <span className="font-bold text-green-400">{currentQuestion.debugInfo.correctAnswerText}</span>
              </div>
              <div className="text-slate-300">
                <span className="text-slate-500 font-mono mr-2">SRC:</span>
                <span className="text-blue-300">{currentQuestion.debugInfo.source}</span>
              </div>
            </div>
          )}
        </div>

        <div className="w-full space-y-4">
          {currentQuestion.options.map((option, index) => (
            <button
              key={index}
              onClick={() => handleOptionSelect(currentQuestion.id, index)}
              className={`w-full p-4 rounded-xl border-2 text-left transition-all ${
                answers[currentQuestion.id] === index
                  ? 'border-indigo-500 bg-indigo-500/10 text-indigo-300'
                  : 'border-slate-700 hover:bg-slate-800 text-slate-300 hover:border-slate-600'
              }`}
            >
              <div className="flex items-center">
                <div className={`w-6 h-6 rounded-full border-2 mr-4 flex items-center justify-center ${
                  answers[currentQuestion.id] === index
                    ? 'border-indigo-500'
                    : 'border-slate-600'
                }`}>
                  {answers[currentQuestion.id] === index && <div className="w-3 h-3 bg-indigo-500 rounded-full" />}
                </div>
                {option}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="p-4 border-t border-slate-800 bg-slate-900">
        <div className="max-w-2xl mx-auto flex justify-end">
          <button
            onClick={handleNext}
            disabled={answers[currentQuestion.id] === undefined || submitting}
            className={`px-8 py-3 rounded-xl font-bold text-white transition-all ${
              answers[currentQuestion.id] === undefined
                ? 'bg-slate-700 cursor-not-allowed text-slate-500'
                : 'bg-indigo-600 hover:bg-indigo-500 shadow-[0_4px_0_0_#3730a3] active:shadow-none active:translate-y-1'
            }`}
          >
            {submitting ? '提交中...' : (currentStep < questions.length - 1 ? '下一題' : '提交測驗')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default PlacementTestComponent;
