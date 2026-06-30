import React, { useState, useEffect } from 'react';
import api from '../services/api';

const LearningMode = ({ chapter, onClose, onComplete }) => {
  const [questions, setQuestions] = useState(chapter.data.questions || []);
  const [generating, setGenerating] = useState(false);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState(null);
  const [isCorrect, setIsCorrect] = useState(null);
  const [completed, setCompleted] = useState(false);
  const [correctCount, setCorrectCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [lives, setLives] = useState(5);

  useEffect(() => {
    let isMounted = true;
    if (questions.length === 0) {
      setGenerating(true);
      api.generateQuiz(chapter.id)
        .then(data => {
          if (isMounted && data.questions && data.questions.length > 0) {
            setQuestions(prev => {
              // Prevent overwriting if questions were already loaded by a concurrent request
              if (prev.length > 0) return prev;
              return data.questions;
            });
          }
        })
        .catch(err => {
          if (isMounted) console.error("Error generating quiz:", err);
        })
        .finally(() => {
          if (isMounted) setGenerating(false);
        });
    }
    return () => {
      isMounted = false;
    };
  }, [chapter.id]);

  const currentQuestion = questions[currentQuestionIndex];

  const handleOptionClick = (index) => {
    if (isCorrect !== null) return; // Prevent changing answer after submission
    setSelectedOption(index);
  };

  const handleCheck = () => {
    if (selectedOption === null) return;
    
    const correct = selectedOption === currentQuestion.correctAnswer;
    setIsCorrect(correct);
    if (correct) {
      setCorrectCount(prev => prev + 1);
    } else {
      setLives(prev => Math.max(0, prev - 1));
      // Record mistake
      api.recordMistake({
        question_data: {
          ...currentQuestion,
          node_id: chapter.id,
          entity_name: chapter.data.label
        },
        user_answer_index: selectedOption
      }).catch(err => console.error("Failed to record mistake:", err));
    }
  };

  const handleNext = () => {
    if (currentQuestionIndex < questions.length - 1) {
      setCurrentQuestionIndex(currentQuestionIndex + 1);
      setSelectedOption(null);
      setIsCorrect(null);
    } else {
      setCompleted(true);
    }
  };

  const handleComplete = async () => {
    setSubmitting(true);
    try {
      await api.completeNode(chapter.id);
      if (onComplete) {
        onComplete();
      } else {
        onClose();
      }
    } catch (error) {
      console.error("Failed to complete node", error);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  if (generating) {
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

  if (questions.length === 0) {
    return (
      <div className="fixed inset-0 bg-slate-900 bg-opacity-95 flex items-center justify-center z-50">
        <div className="bg-slate-800 p-8 rounded-xl max-w-md w-full text-center border border-slate-700">
          <h2 className="text-2xl font-bold text-white mb-4">暫無題目</h2>
          <p className="text-slate-300 mb-6">本章節尚未建立測驗題目，且生成失敗。</p>
          <button 
            onClick={onClose}
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold transition-colors shadow-[0_4px_0_0_#3730a3]"
          >
            返回
          </button>
        </div>
      </div>
    );
  }

  if (completed) {
    // If we have remedialInfo, it means the quiz was submitted and failed
    const percentage = (correctCount / questions.length) * 100;
    const passed = percentage >= 60;

    return (
      <div className="fixed inset-0 bg-slate-900 bg-opacity-95 flex items-center justify-center z-50">
        <div className="bg-slate-800 p-8 rounded-xl max-w-md w-full text-center animate-fade-in border border-slate-700">
          <div className="text-6xl mb-4">{passed ? '🎉' : '💪'}</div>
          <h2 className="text-2xl font-bold text-white mb-4">{passed ? '單元完成！' : '再接再厲！'}</h2>
          <div className="mb-6 space-y-2">
             <p className={`text-xl font-bold ${passed ? 'text-emerald-400' : 'text-red-400'}`}>
               答對 {correctCount} / {questions.length} 題 ({Math.round(percentage)}%)
             </p>
             <p className="text-slate-300">
               {passed 
                 ? `恭喜你完成了 ${chapter.data.label} 的學習單元。` 
                 : `很遺憾，您需要達到 60% 的正確率才能解鎖下一個單元。`}
             </p>
             {!passed && remedialInfo && (
                <div className="mt-4 p-4 bg-red-900/20 border border-red-800 rounded-lg">
                    <h3 className="text-red-400 font-bold mb-2">💡 建議先學習</h3>
                    <p className="text-slate-300 text-sm mb-3">{remedialInfo.remedial_message}</p>
                    {remedialInfo.remedial_nodes && remedialInfo.remedial_nodes.length > 0 && (
                      <div className="space-y-2">
                          {remedialInfo.remedial_nodes.map(nodeId => (
                              <div key={nodeId} className="w-full text-left p-2 bg-slate-800 rounded border border-slate-700 text-sm text-slate-300">
                                  推薦先備節點：{nodeId}
                              </div>
                          ))}
                      </div>
                    )}
                </div>
            )}
          </div>
          {passed ? (
            <button 
              onClick={handleComplete}
              disabled={submitting}
              className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl font-bold transition-colors shadow-[0_4px_0_0_#3730a3] disabled:opacity-50"
            >
              {submitting ? '處理中...' : '繼續學習'}
            </button>
          ) : (
            <button 
              onClick={remedialInfo ? onClose : handleComplete}
              disabled={submitting}
              className="w-full py-3 bg-slate-600 hover:bg-slate-500 text-white rounded-xl font-bold transition-colors shadow-[0_4px_0_0_#475569] disabled:opacity-50"
            >
              {submitting ? '處理中...' : (remedialInfo ? '返回重試' : '送出成績並查看建議')}
            </button>
          )}
        </div>
      </div>
    );
  }

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
          <div className="h-4 bg-slate-700 rounded-full overflow-hidden">
            <div 
              className="h-full bg-cyan-500 transition-all duration-300"
              style={{ width: `${((currentQuestionIndex) / questions.length) * 100}%` }}
            />
          </div>
        </div>
        <div className="text-red-500 font-bold flex items-center gap-1">
          <span>❤️</span> {lives}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 max-w-2xl mx-auto w-full">
        <h2 className="text-2xl font-bold text-white mb-8 text-center leading-relaxed">
          {currentQuestion.text || currentQuestion.question}
        </h2>

        {currentQuestion.debugInfo && (
            <div className="mb-6 p-3 bg-red-900/30 border border-red-500/50 rounded-lg text-left text-sm inline-block max-w-lg mx-auto w-full">
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

        <div className="w-full space-y-4">
          {currentQuestion.options.map((option, index) => (
            <button
              key={index}
              onClick={() => handleOptionClick(index)}
              disabled={isCorrect !== null}
              className={`w-full p-4 rounded-xl border-2 text-left transition-all ${
                selectedOption === index
                  ? isCorrect === null
                    ? 'border-cyan-500 bg-cyan-500/10 text-cyan-400'
                    : isCorrect && index === currentQuestion.correctAnswer
                      ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                      : 'border-red-500 bg-red-500/10 text-red-400'
                  : 'border-slate-700 hover:bg-slate-800 text-slate-300 hover:border-slate-600'
              } ${
                isCorrect !== null && index === currentQuestion.correctAnswer && selectedOption !== index
                  ? 'border-emerald-500 bg-emerald-500/10 text-emerald-400'
                  : ''
              }`}
            >
              <div className="flex items-center">
                <div className={`w-6 h-6 rounded-md border-2 mr-4 flex items-center justify-center ${
                  selectedOption === index
                    ? 'border-current'
                    : 'border-slate-600'
                }`}>
                  {selectedOption === index && <div className="w-3 h-3 bg-current rounded-sm" />}
                </div>
                {option}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className={`p-4 border-t border-slate-800 ${
        isCorrect === true ? 'bg-emerald-900/20 border-emerald-900' : 
        isCorrect === false ? 'bg-red-900/20 border-red-900' : 'bg-slate-900'
      }`}>
        <div className="max-w-2xl mx-auto flex justify-between items-center">
          {isCorrect === true && (
            <div className="flex items-center text-emerald-500 font-bold text-xl">
              <div className="w-8 h-8 bg-emerald-500 rounded-full flex items-center justify-center text-slate-900 mr-3">✓</div>
              太棒了！
            </div>
          )}
          {isCorrect === false && (
            <div className="flex items-center text-red-500 font-bold text-xl">
              <div className="w-8 h-8 bg-red-500 rounded-full flex items-center justify-center text-white mr-3">✕</div>
              正確答案：{currentQuestion.options[currentQuestion.correctAnswer]}
            </div>
          )}
          <div className="flex-1" />
          <button
            onClick={isCorrect !== null ? handleNext : handleCheck}
            disabled={selectedOption === null}
            className={`px-8 py-3 rounded-xl font-bold text-white transition-all ${
              selectedOption === null
                ? 'bg-slate-700 cursor-not-allowed text-slate-500'
                : isCorrect === null
                  ? 'bg-indigo-600 hover:bg-indigo-500 shadow-[0_4px_0_0_#3730a3]'
                  : isCorrect
                    ? 'bg-indigo-600 hover:bg-indigo-500 shadow-[0_4px_0_0_#3730a3]'
                    : 'bg-indigo-600 hover:bg-indigo-500 shadow-[0_4px_0_0_#3730a3]'
            }`}
          >
            {isCorrect !== null ? (currentQuestionIndex < questions.length - 1 ? '繼續' : '完成') : '檢查'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LearningMode;
